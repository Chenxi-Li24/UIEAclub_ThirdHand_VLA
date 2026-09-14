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
const VOICE_PROTOCOL = 'thirdhand.voice.v1';
const PLAN_PROTOCOL = 'thirdhand.plan.v1';

function writeJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function createWebGateway(options = {}) {
  const config = { ...loadConfig(options.env), ...options };
  const robotProxy = new RobotProxy(config.robotWsUrl, config.language);
  const visionProxy = new VisionProxy(config.visionWsUrl);
  const voiceProxy = new WebSocketProxy(config.voiceWsUrl, {
    subprotocol: VOICE_PROTOCOL,
  });
  const planProxy = new WebSocketProxy(config.orchestratorWsUrl, {
    subprotocol: PLAN_PROTOCOL,
  });
  const connections = new Set();
  let closing = false;

  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method === 'GET' && pathname === '/api/runtime-config') {
      writeJson(response, 200, {
        voice: { endpoint: '/voice', protocol: VOICE_PROTOCOL },
        plan: { endpoint: '/plan', protocol: PLAN_PROTOCOL },
        vision: { endpoint: '/vision' },
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
          orchestrator: { url: config.orchestratorWsUrl },
        },
      });
      return;
    }
    const visionGetRoutes = new Set([
      '/api/vision/status',
      '/camera/xvisio/raw',
      '/camera/xvisio/vision',
      '/camera/xvisio/depth',
    ]);
    const visionPostRoutes = new Set([
      '/api/vision/select',
      '/api/vision/release',
    ]);
    if ((request.method === 'GET' && visionGetRoutes.has(pathname)) ||
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
  const planWss = new WebSocketServer({
    noServer: true,
    handleProtocols(protocols) {
      return protocols.has(PLAN_PROTOCOL) ? PLAN_PROTOCOL : false;
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
    if (request.url === '/plan') {
      const requestedProtocols = String(
        request.headers['sec-websocket-protocol'] || '',
      ).split(',').map(value => value.trim());
      if (!requestedProtocols.includes(PLAN_PROTOCOL)) {
        socket.write('HTTP/1.1 426 Upgrade Required\r\nConnection: close\r\n\r\n');
        socket.destroy();
        return;
      }
      planWss.handleUpgrade(
        request,
        socket,
        head,
        ws => planWss.emit('connection', ws),
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
  robotWss.on('connection', socket => robotProxy.attach(socket));
  visionWss.on('connection', socket => visionProxy.attach(socket));
  voiceWss.on('connection', socket => voiceProxy.attach(socket));
  planWss.on('connection', socket => planProxy.attach(socket));

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
      robotProxy.close();
      visionProxy.close();
      voiceProxy.close();
      planProxy.close();
      // MJPEG responses are intentionally long-lived. Tear down every inbound
      // transport so an active camera feed cannot block a supervised stop.
      for (const socket of connections) socket.destroy();
      await new Promise(resolve => robotWss.close(resolve));
      await new Promise(resolve => visionWss.close(resolve));
      await new Promise(resolve => voiceWss.close(resolve));
      await new Promise(resolve => planWss.close(resolve));
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

module.exports = { createWebGateway };
