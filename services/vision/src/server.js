#!/usr/bin/env node
'use strict';

const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');
const { CameraProcess } = require('./camera-process');
const { loadConfig } = require('./config');

const STREAMS = new Map([
  ['/camera/xvisio/raw', 'raw'],
  ['/camera/xvisio/vision', 'vision'],
  ['/camera/xvisio/depth', 'depth'],
]);

function writeJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readJson(request, maxBytes = 16 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on('data', chunk => {
      size += chunk.length;
      if (size > maxBytes) {
        const error = new Error('request body too large');
        error.statusCode = 413;
        reject(error);
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        const error = new Error('invalid JSON');
        error.statusCode = 400;
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function sendTargetSelection(camera, stableId, requestId) {
  const current = camera.status()?.selection || {};
  if (current.stableId === stableId) return true;
  if (Number.isSafeInteger(current.stableId)) {
    const released = camera.send({
      type: 'release_target',
      requestId: current.requestId,
    });
    if (!released) return false;
  }
  return camera.send({ type: 'select_target', stableId, requestId });
}

function streamUnavailable(status, kind) {
  if (status.camera.status !== 'ready') {
    return {
      code: 'camera_unavailable',
      msg: status.camera.error || 'XVisio camera is not ready',
    };
  }
  if (kind === 'vision' && status.inference.status !== 'ready') {
    return {
      code: 'inference_unavailable',
      msg: status.inference.error || 'Vision inference is not ready',
    };
  }
  return null;
}

function createVisionService(options = {}) {
  const config = { ...loadConfig(options.env), ...options };
  const camera = options.camera || new CameraProcess(config);
  let closing = false;

  const server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method === 'GET' &&
        (pathname === '/health' || pathname === '/api/vision/status')) {
      writeJson(response, 200, {
        status: 'ready',
        serviceId: 'vision',
        robotControlEnabled: false,
        ...camera.status(),
      });
      return;
    }

    if (request.method === 'GET' && pathname === '/api/vision/observation') {
      const observation = camera.observation?.() || null;
      writeJson(response, observation ? 200 : 503, observation || {
        code: 'observation_unavailable',
        robotControlEnabled: false,
      });
      return;
    }

    const targetMatch = pathname.match(/^\/api\/vision\/targets\/([1-5])$/);
    if (request.method === 'GET' && targetMatch) {
      const stableId = Number(targetMatch[1]);
      const observation = camera.observation?.(stableId) || null;
      writeJson(response, observation ? 200 : 404, observation || {
        code: 'target_not_observed',
        stableId,
        robotControlEnabled: false,
      });
      return;
    }

    if (request.method === 'GET' && STREAMS.has(pathname)) {
      const kind = STREAMS.get(pathname);
      const unavailable = streamUnavailable(camera.status(), kind);
      if (unavailable) {
        writeJson(response, 503, unavailable);
        return;
      }
      response.writeHead(200, {
        'content-type': 'multipart/x-mixed-replace; boundary=frame',
        'cache-control': 'no-store, no-cache, must-revalidate',
        connection: 'close',
      });
      if (!camera.subscribe(kind, response)) {
        response.end();
        return;
      }
      response.on('close', () => camera.unsubscribe(kind, response));
      return;
    }

    if (request.method === 'POST' && pathname === '/api/vision/select') {
      try {
        const body = await readJson(request);
        if (!Number.isSafeInteger(body.stableId) ||
            body.stableId < 1 || body.stableId > 5) {
          writeJson(response, 400, {
            accepted: false,
            code: 'invalid_target',
          });
          return;
        }
        const requestId = (
          typeof body.requestId === 'string' && body.requestId.length > 0
            && body.requestId.length <= 128
        ) ? body.requestId : randomUUID();
        const accepted = sendTargetSelection(camera, body.stableId, requestId);
        writeJson(response, accepted ? 202 : 503, {
          accepted,
          stableId: body.stableId,
          requestId,
          robotControlEnabled: false,
        });
      } catch (error) {
        writeJson(response, error.statusCode || 400, {
          accepted: false,
          code: 'invalid_request',
          msg: error.message,
        });
      }
      return;
    }

    if (request.method === 'POST' && pathname === '/api/vision/release') {
      const accepted = camera.send({ type: 'release_target' });
      writeJson(response, accepted ? 202 : 503, {
        accepted,
        robotControlEnabled: false,
      });
      return;
    }

    writeJson(response, 404, { error: 'not_found' });
  });

  const wss = new WebSocketServer({
    noServer: true,
    maxPayload: 16 * 1024,
  });
  server.on('upgrade', (request, socket, head) => {
    if (request.url !== '/ws') {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(
      request,
      socket,
      head,
      ws => wss.emit('connection', ws),
    );
  });
  wss.on('connection', socket => {
    socket.send(JSON.stringify({
      type: 'runtime_status',
      ...camera.status(),
      robotControlEnabled: false,
    }));
    socket.on('message', data => {
      let message;
      try {
        message = JSON.parse(data.toString('utf8'));
      } catch {
        socket.close(1007, 'invalid JSON');
        return;
      }
      let accepted = false;
      if (message?.type === 'select_target' &&
          Number.isSafeInteger(message.stableId) &&
          message.stableId >= 1 && message.stableId <= 5) {
        const requestId = (
          typeof message.requestId === 'string' && message.requestId.length > 0
            && message.requestId.length <= 128
        ) ? message.requestId : randomUUID();
        accepted = sendTargetSelection(camera, message.stableId, requestId);
      } else if (message?.type === 'release_target') {
        accepted = camera.send({
          type: 'release_target',
          requestId: message.requestId,
        });
      }
      if (!accepted && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({
          type: 'command_rejected',
          code: 'invalid_or_unavailable',
        }));
      }
    });
  });

  const broadcast = message => {
    const payload = JSON.stringify({
      ...message,
      robotControlEnabled: false,
    });
    for (const client of wss.clients) {
      if (client.readyState === WebSocket.OPEN) client.send(payload);
    }
  };
  camera.on?.('event', broadcast);
  camera.on?.('log', message => {
    console.error(`[Vision] ${message.message}`);
  });

  return {
    async start() {
      camera.start();
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(config.port, config.host, resolve);
      });
      fs.mkdirSync(path.dirname(config.readyFile), { recursive: true });
      const temporary = `${config.readyFile}.tmp`;
      fs.writeFileSync(temporary, `${JSON.stringify({
        ready: true,
        serviceId: 'vision',
        pid: process.pid,
      })}\n`);
      fs.renameSync(temporary, config.readyFile);
      return server.address();
    },

    async close() {
      if (closing) return;
      closing = true;
      camera.off?.('event', broadcast);
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await camera.close();
      await new Promise(resolve => {
        if (server.listening) server.close(resolve);
        else resolve();
      });
      try {
        fs.unlinkSync(config.readyFile);
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    },
  };
}

async function main() {
  const service = createVisionService();
  const address = await service.start();
  console.log(
    `ThirdHand Vision Service listening on http://${address.address}:${address.port}`,
  );

  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    await service.close();
  };
  process.on('SIGINT', () => stop().then(() => process.exit(0)));
  process.on('SIGTERM', () => stop().then(() => process.exit(0)));
}

if (require.main === module) {
  main().catch(error => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}

module.exports = {
  createVisionService,
  readJson,
  streamUnavailable,
};
