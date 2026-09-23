#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { WebSocketServer } = require('ws');
const { loadConfig } = require('./config');
const { proxyHttpRequest } = require('./http-proxy');
const { RobotProxy } = require('./robot-proxy');
const { serveStatic } = require('./static-server');
const { VisionProxy } = require('./vision-proxy');
const { WebSocketProxy } = require('./websocket-proxy');
const { ActiveDepthCoordinator } = require('./active-depth/coordinator');
const { ExecutionClient } = require('./active-depth/execution-client');
const { VisionClient } = require('./active-depth/vision-client');
const VOICE_PROTOCOL = 'thirdhand.voice.v1';

function writeJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readJson(request, maximumBytes = 16 * 1024) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let tooLarge = false;
    request.on('data', chunk => {
      size += chunk.length;
      if (size > maximumBytes) tooLarge = true;
      else chunks.push(chunk);
    });
    request.on('end', () => {
      if (tooLarge) {
        const error = new Error('Request body is too large');
        error.code = 'body_too_large';
        reject(error);
        return;
      }
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); }
      catch {
        const error = new Error('Request body is invalid JSON');
        error.code = 'invalid_json';
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function loadMount(file) {
  const document = JSON.parse(fs.readFileSync(file, 'utf8'));
  return {
    matrix_4x4: document.matrix_4x4 || document.T_flange_camera?.matrix_4x4,
    camera_mount_id: document.camera_mount_id || document.camera?.camera_mount_id,
    registration_id: document.registration_id || document.camera?.registration_id,
    physicalValidation: document.physical_validation?.status || null,
  };
}

function exactKeys(body, keys) {
  return body && typeof body === 'object' && !Array.isArray(body)
    && Object.keys(body).length === keys.length
    && keys.every(key => Object.prototype.hasOwnProperty.call(body, key));
}

function createWebGateway(options = {}) {
  const config = { ...loadConfig(options.env), ...options };
  const robotProxy = options.robotProxy || new RobotProxy(config.robotWsUrl, config.language);
  const visionProxy = options.visionProxy || new VisionProxy(config.visionWsUrl);
  const voiceProxy = options.voiceProxy || new WebSocketProxy(config.voiceWsUrl, {
    subprotocol: VOICE_PROTOCOL,
  });
  let coordinator = options.coordinator;
  let activeDepthReason = null;
  if (!coordinator) {
    try {
      const mount = loadMount(config.activeDepthMountFile);
      const executionClient = new ExecutionClient({
        endpoint: config.robotExecutionWsUrl,
        tokenFile: config.robotExecutionTokenFile,
      });
      const visionClient = new VisionClient({ baseUrl: config.visionHttpUrl });
      coordinator = new ActiveDepthCoordinator({
        executionClient, visionClient, mount,
        getRobotState: () => robotProxy.getRobotState(),
      });
    } catch (error) {
      activeDepthReason = error.code || 'active_depth_configuration_invalid';
    }
  }
  const activeDepthReady = Boolean(coordinator);
  const connections = new Set();
  let closing = false;

  if (coordinator) coordinator.on('status', status => robotProxy.broadcast(status));

  const server = http.createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method === 'GET' && pathname === '/api/runtime-config') {
      writeJson(response, 200, {
        voice: { endpoint: '/voice', protocol: VOICE_PROTOCOL },
        vision: { endpoint: '/vision' },
        activeDepth: { ready: activeDepthReady, startEndpoint: '/api/active-depth/start' },
        language: {
          executionBackend: 'formal-3000-upstream',
          directional: {
            enabled: config.language.directionalEnabled,
            realControlEnabled: config.language.directionalRealControlEnabled,
          },
        },
      });
      return;
    }
    if (request.method === 'GET' && pathname === '/health') {
      writeJson(response, 200, {
        status: 'ready',
        serviceId: 'web',
        dependencies: {
          robot: { url: config.robotWsUrl },
          vision: { url: config.visionHttpUrl },
          voice: { url: config.voiceWsUrl },
          bottlePick: { url: config.language.vaHttpUrl },
          activeDepth: { ready: activeDepthReady, reason: activeDepthReason },
        },
      });
      return;
    }
    if (request.method === 'GET' && pathname === '/api/active-depth/status') {
      writeJson(response, 200, coordinator?.status() || {
        type: 'active_depth.status', phase: 'unavailable', active: false,
        reason: activeDepthReason || 'active_depth_unavailable',
      });
      return;
    }
    if (request.method === 'POST'
        && (pathname === '/api/active-depth/start' || pathname === '/api/active-depth/stop')) {
      if (!coordinator) {
        writeJson(response, 503, { error: activeDepthReason || 'active_depth_unavailable' });
        return;
      }
      try {
        const body = await readJson(request);
        if (pathname.endsWith('/start')) {
          if (!exactKeys(body, ['stableId']) || !Number.isSafeInteger(body.stableId)
              || body.stableId < 1 || body.stableId > 5) {
            writeJson(response, 400, { error: 'request_invalid' });
            return;
          }
          writeJson(response, 202, await coordinator.start(body.stableId));
          return;
        }
        if (!exactKeys(body, ['sessionId']) || typeof body.sessionId !== 'string'
            || body.sessionId.length === 0) {
          writeJson(response, 400, { error: 'request_invalid' });
          return;
        }
        writeJson(response, 200, await coordinator.stop(body.sessionId));
      } catch (error) {
        if (response.headersSent) return;
        const status = error.code === 'body_too_large' ? 413
          : error.code === 'active_depth_active' ? 409
            : ['invalid_json', 'stable_id_invalid'].includes(error.code) ? 400 : 500;
        writeJson(response, status, { error: error.code || 'active_depth_error' });
      }
      return;
    }
    const visionGetRoutes = new Set([
      '/api/vision/status',
      '/api/vision/observation',
      '/camera/xvisio/raw',
      '/camera/xvisio/vision',
      '/camera/xvisio/depth',
    ]);
    const visionPostRoutes = new Set([
      '/api/vision/select',
      '/api/vision/release',
    ]);
    const isVisionTargetRoute = pathname.startsWith('/api/vision/targets/')
      && /^[1-5]$/.test(pathname.slice('/api/vision/targets/'.length));
    if ((request.method === 'GET' && (visionGetRoutes.has(pathname) || isVisionTargetRoute)) ||
        (request.method === 'POST' && visionPostRoutes.has(pathname))) {
      proxyHttpRequest(request, response, config.visionHttpUrl, pathname);
      return;
    }
    if (serveStatic(request, response, config)) return;
    writeJson(response, 404, { error: 'not_found' });
  });
  server.on('connection', socket => {
    connections.add(socket);
    socket.once('close', () => connections.delete(socket));
  });

  const robotWss = new WebSocketServer({ noServer: true });
  const visionWss = new WebSocketServer({ noServer: true });
  const voiceWss = new WebSocketServer({
    noServer: true,
    handleProtocols(protocols) {
      return protocols.has(VOICE_PROTOCOL) ? VOICE_PROTOCOL : false;
    },
  });
  server.on('upgrade', (request, socket, head) => {
    if (request.url === '/ws') {
      robotWss.handleUpgrade(
        request,
        socket,
        head,
        ws => robotWss.emit('connection', ws),
      );
      return;
    }
    if (request.url === '/vision') {
      visionWss.handleUpgrade(
        request,
        socket,
        head,
        ws => visionWss.emit('connection', ws),
      );
      return;
    }
    if (request.url !== '/voice') {
      socket.destroy();
      return;
    }
    const requestedProtocols = String(
      request.headers['sec-websocket-protocol'] || '',
    ).split(',').map(value => value.trim());
    if (!requestedProtocols.includes(VOICE_PROTOCOL)) {
      socket.write('HTTP/1.1 426 Upgrade Required\r\n\r\n');
      socket.destroy();
      return;
    }
    voiceWss.handleUpgrade(
      request,
      socket,
      head,
      ws => voiceWss.emit('connection', ws),
    );
  });
  robotWss.on('connection', socket => {
    robotProxy.attach(socket);
    if (coordinator && socket.readyState === socket.OPEN) {
      socket.send(JSON.stringify(coordinator.status()));
    }
  });
  visionWss.on('connection', socket => visionProxy.attach(socket));
  voiceWss.on('connection', socket => voiceProxy.attach(socket));

  return {
    async start() {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(config.port, config.host, resolve);
      });
      fs.mkdirSync(path.dirname(config.readyFile), { recursive: true });
      fs.writeFileSync(config.readyFile, `${JSON.stringify({
        ready: true,
        serviceId: 'web',
        pid: process.pid,
      })}\n`);
      return server.address();
    },
    async close() {
      if (closing) return;
      closing = true;
      if (coordinator) await coordinator.close();
      robotProxy.close();
      visionProxy.close();
      voiceProxy.close();
      // MJPEG responses are intentionally long-lived. Tear down every inbound
      // transport so an active camera feed cannot block a supervised stop.
      for (const socket of connections) socket.destroy();
      await new Promise(resolve => robotWss.close(resolve));
      await new Promise(resolve => visionWss.close(resolve));
      await new Promise(resolve => voiceWss.close(resolve));
      await new Promise(resolve => server.listening ? server.close(resolve) : resolve());
      try {
        fs.unlinkSync(config.readyFile);
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    },
  };
}

async function main() {
  const gateway = createWebGateway();
  const address = await gateway.start();
  console.log(`ThirdHand Web Gateway listening on http://${address.address}:${address.port}`);

  let stopping = false;
  const stop = async () => {
    if (stopping) return;
    stopping = true;
    await gateway.close();
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

module.exports = { createWebGateway, exactKeys, loadMount, readJson };
