#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { WebSocketServer } = require('ws');
const { loadConfig } = require('./config');
const { RobotProxy } = require('./robot-proxy');
const { serveStatic } = require('./static-server');

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
  const robotProxy = new RobotProxy(config.robotWsUrl);
  let closing = false;

  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method === 'GET' && pathname === '/health') {
      writeJson(response, 200, {
        status: 'ready',
        serviceId: 'web',
        dependencies: {
          robot: { url: config.robotWsUrl },
          vision: { status: 'not_migrated' },
          voice: { status: 'not_migrated' },
        },
      });
      return;
    }
    if (pathname.startsWith('/api/vision') || pathname.startsWith('/camera/')) {
      writeJson(response, 503, {
        code: 'service_unavailable',
        service: 'vision',
        msg: 'Vision Service has not been migrated into the unified project yet',
      });
      return;
    }
    if (serveStatic(request, response, config)) return;
    writeJson(response, 404, { error: 'not_found' });
  });

  const wss = new WebSocketServer({ noServer: true });
  server.on('upgrade', (request, socket, head) => {
    if (request.url !== '/ws') {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(request, socket, head, ws => wss.emit('connection', ws));
  });
  wss.on('connection', socket => robotProxy.attach(socket));

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
      await new Promise(resolve => wss.close(resolve));
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
