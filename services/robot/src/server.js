#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');
const { loadConfig } = require('./config');
const { ExecutionGateway } = require('./execution-gateway');
const { loadExecutionToken, tokenMatches } = require('./execution-token');
const { RobotController } = require('./robot-controller');

function writeJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function createRobotService(options = {}) {
  const defaults = loadConfig(options.env);
  const config = {
    ...defaults,
    ...options,
    robot: { ...defaults.robot, ...(options.robot || {}) },
  };
  const controller = new RobotController(config.robot);
  const executionToken = loadExecutionToken({
    token: options.executionToken,
    tokenFile: config.executionTokenFile,
  });
  const executionGateway = new ExecutionGateway(controller);
  const sockets = new Set();
  const executionSockets = new Set();
  let closing = false;

  const server = http.createServer((request, response) => {
    if (request.method === 'GET' && request.url === '/health') {
      writeJson(response, 200, {
        ...controller.health(),
        execution: { available: executionToken.available, reason: executionToken.reason },
      });
      return;
    }
    writeJson(response, 404, { error: 'not_found' });
  });
  const wss = new WebSocketServer({ noServer: true });
  const executionWss = new WebSocketServer({ noServer: true });

  controller.on('message', message => {
    const payload = JSON.stringify(message);
    for (const socket of sockets) {
      if (socket.readyState === WebSocket.OPEN) socket.send(payload);
    }
  });

  server.on('upgrade', (request, socket, head) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (pathname === '/execution') {
      if (!executionToken.available
        || !tokenMatches(executionToken.token, request.headers['x-thirdhand-execution-token'])) {
        socket.write('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\nContent-Length: 0\r\n\r\n');
        socket.destroy();
        return;
      }
      executionWss.handleUpgrade(
        request,
        socket,
        head,
        ws => executionWss.emit('connection', ws),
      );
      return;
    }
    if (pathname !== '/ws') {
      socket.destroy();
      return;
    }
    wss.handleUpgrade(request, socket, head, ws => wss.emit('connection', ws));
  });

  wss.on('connection', socket => {
    sockets.add(socket);
    socket.send(JSON.stringify(controller.configMessage()));
    socket.on('message', data => {
      let message;
      try {
        message = JSON.parse(data.toString('utf8'));
      } catch {
        socket.send(JSON.stringify({
          type: 'error',
          code: 'invalid_json',
          msg: 'Invalid JSON message',
        }));
        return;
      }
      if (message?.type === 'capability_request') {
        if (message.schema !== 'thirdhand-robot-capability-v1'
            || typeof message.nonce !== 'string' || !message.nonce) {
          socket.send(JSON.stringify({
            type: 'error',
            code: 'capability_request_invalid',
            msg: 'Invalid capability request',
          }));
          return;
        }
        socket.send(JSON.stringify(controller.capabilityResponse(message.nonce)));
        return;
      }
      controller.handleCommand(message, reply => {
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(reply));
      });
    });
    socket.on('close', () => sockets.delete(socket));
  });
  executionWss.on('connection', socket => {
    executionSockets.add(socket);
    executionGateway.attach(socket);
    socket.on('close', () => executionSockets.delete(socket));
  });

  return {
    controller,
    async start() {
      await controller.start();
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(config.port, config.host, resolve);
      });
      fs.mkdirSync(path.dirname(config.readyFile), { recursive: true });
      fs.writeFileSync(config.readyFile, `${JSON.stringify({
        ready: true,
        serviceId: 'robot',
        pid: process.pid,
      })}\n`);
      return server.address();
    },
    async close() {
      if (closing) return;
      closing = true;
      for (const socket of sockets) socket.terminate();
      for (const socket of executionSockets) socket.terminate();
      executionGateway.close();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => executionWss.close(resolve));
      await new Promise(resolve => server.listening ? server.close(resolve) : resolve());
      await controller.shutdown();
      try {
        fs.unlinkSync(config.readyFile);
      } catch (error) {
        if (error.code !== 'ENOENT') throw error;
      }
    },
  };
}

async function main() {
  const service = createRobotService();
  const address = await service.start();
  console.log(`ThirdHand Robot Service listening on ${address.address}:${address.port}`);

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

module.exports = { createRobotService };
