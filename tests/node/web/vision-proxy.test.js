'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');

const { createWebGateway } = require('../../../apps/web/src/server');

async function createVisionStub() {
  const received = [];
  const server = http.createServer((request, response) => {
    if (request.url === '/api/vision/status') {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end(JSON.stringify({
        status: 'ready',
        camera: { status: 'ready', sequence: 7 },
        inference: { status: 'ready', error: null },
      }));
      return;
    }
    if (request.url === '/camera/xvisio/raw') {
      response.writeHead(200, {
        'content-type': 'multipart/x-mixed-replace; boundary=frame',
      });
      response.end(
        '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\njpeg\r\n',
      );
      return;
    }
    if (request.url === '/camera/xvisio/vision') {
      response.writeHead(200, {
        'content-type': 'multipart/x-mixed-replace; boundary=frame',
      });
      response.write(
        '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\njpeg\r\n',
      );
      return;
    }
    response.writeHead(404);
    response.end();
  });
  const wss = new WebSocketServer({ noServer: true });
  server.on('upgrade', (request, socket, head) => {
    if (request.url !== '/ws') return socket.destroy();
    wss.handleUpgrade(request, socket, head, ws => wss.emit('connection', ws));
  });
  wss.on('connection', socket => {
    socket.send(JSON.stringify({
      type: 'detection_result',
      targets: [{ stableId: 3, label: 'bottle', selected: false }],
    }));
    socket.on('message', data => received.push(JSON.parse(data.toString('utf8'))));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  return {
    received,
    httpUrl: `http://127.0.0.1:${port}`,
    wsUrl: `ws://127.0.0.1:${port}/ws`,
    async close() {
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

test('vision streams and events are proxied without robot access', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-vision-proxy-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(publicDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand</h1>');

  const vision = await createVisionStub();
  const gateway = createWebGateway({
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: 'ws://127.0.0.1:9/ws',
    voiceWsUrl: 'ws://127.0.0.1:9/voice',
    visionHttpUrl: vision.httpUrl,
    visionWsUrl: vision.wsUrl,
  });
  t.after(async () => {
    await gateway.close();
    await vision.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const status = await fetch(`${origin}/api/vision/status`);
  assert.equal(status.status, 200);
  assert.equal((await status.json()).camera.status, 'ready');

  const raw = await fetch(`${origin}/camera/xvisio/raw`);
  assert.equal(raw.status, 200);
  assert.match(raw.headers.get('content-type'), /boundary=frame/);
  assert.match(await raw.text(), /jpeg/);

  const browser = new WebSocket(`ws://127.0.0.1:${address.port}/vision`);
  const event = await new Promise((resolve, reject) => {
    browser.once('message', data => resolve(JSON.parse(data.toString('utf8'))));
    browser.once('error', reject);
  });
  assert.equal(event.targets[0].stableId, 3);
  browser.send(JSON.stringify({ type: 'select_target', stableId: 3 }));
  await new Promise(resolve => setTimeout(resolve, 25));
  assert.deepEqual(vision.received, [{ type: 'select_target', stableId: 3 }]);
  browser.close();

  let streamResponse;
  const streamRequest = http.get(`${origin}/camera/xvisio/vision`);
  await new Promise((resolve, reject) => {
    streamRequest.once('response', response => {
      streamResponse = response;
      response.once('data', resolve);
    });
    streamRequest.once('error', reject);
  });
  const closePromise = gateway.close();
  const closeResult = await Promise.race([
    closePromise.then(() => 'closed'),
    new Promise(resolve => setTimeout(() => resolve('timeout'), 500)),
  ]);
  if (closeResult === 'timeout') {
    streamRequest.destroy();
    streamResponse.destroy();
    await closePromise;
  }
  assert.equal(closeResult, 'closed');
});

test('vision upstream failure remains structured', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-vision-down-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(publicDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand</h1>');
  const gateway = createWebGateway({
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: 'ws://127.0.0.1:9/ws',
    voiceWsUrl: 'ws://127.0.0.1:9/voice',
    visionHttpUrl: 'http://127.0.0.1:9',
    visionWsUrl: 'ws://127.0.0.1:9/ws',
  });
  t.after(async () => {
    await gateway.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const response = await fetch(
    `http://127.0.0.1:${address.port}/api/vision/status`,
  );
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'vision_upstream_unavailable');
});
