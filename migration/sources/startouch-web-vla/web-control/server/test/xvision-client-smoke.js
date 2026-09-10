'use strict';

const assert = require('assert/strict');
const http = require('http');
const { once } = require('events');
const { WebSocketServer } = require('ws');
const { XVisionClient } = require('../xvision-client');

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject);
      resolve(server.address().port);
    });
  });
}

function closeServer(server) {
  return new Promise(resolve => server.close(resolve));
}

function getBody(url) {
  return new Promise((resolve, reject) => {
    http.get(url, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({
        statusCode: response.statusCode,
        contentType: response.headers['content-type'],
        body: Buffer.concat(chunks),
      }));
    }).on('error', reject);
  });
}

function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const poll = () => {
      if (predicate()) return resolve();
      if (Date.now() >= deadline) return reject(new Error('condition timeout'));
      setTimeout(poll, 10);
    };
    poll();
  });
}

(async () => {
  const upstreamHttp = http.createServer((request, response) => {
    if (request.url === '/camera_lumos_vision') {
      response.writeHead(200, {
        'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
      });
      response.end(Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\nvision\r\n'));
      return;
    }
    if (request.url === '/camera_lumos') {
      response.writeHead(200, {
        'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
      });
      response.end(Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\nraw\r\n'));
      return;
    }
    response.writeHead(404).end();
  });
  const upstreamPort = await listen(upstreamHttp);
  const upstreamWs = new WebSocketServer({ server: upstreamHttp, path: '/ws' });
  const commands = [];
  let connections = 0;
  let firstSocket = null;
  upstreamWs.on('connection', socket => {
    connections += 1;
    if (!firstSocket) firstSocket = socket;
    socket.on('message', payload => commands.push(JSON.parse(payload.toString())));
    socket.send(JSON.stringify({
      type: 'detection_result',
      schema: 'thirdhand-va-detection-v2',
      ts: Date.now(),
      targets: [],
    }));
  });

  const client = new XVisionClient({
    baseUrl: `http://127.0.0.1:${upstreamPort}`,
    wsUrl: `ws://127.0.0.1:${upstreamPort}/ws`,
    reconnectMs: 20,
    requestTimeoutMs: 500,
  });
  const detectionPromise = once(client, 'detection_result');
  client.start();
  const [detection] = await detectionPromise;
  assert.equal(detection.schema, 'thirdhand-va-detection-v2');
  await waitFor(() => client.connected);

  assert.equal(client.selectBottle({
    side: 'left',
    ordinal: 2,
    requestId: 'req-1',
  }), true);
  await waitFor(() => commands.length === 1);
  assert.deepEqual(commands[0], {
    cmd: 'select_bottle',
    side: 'left',
    ordinal: 2,
    request_id: 'req-1',
  });
  assert.throws(
    () => client.proxyMjpeg('/arbitrary', {}, {}),
    /unsupported XVisio stream path/i
  );

  const downstream = http.createServer((request, response) => {
    if (request.url === '/vision') {
      client.proxyMjpeg('/camera_lumos_vision', request, response);
      return;
    }
    response.writeHead(404).end();
  });
  const downstreamPort = await listen(downstream);
  const proxied = await getBody(`http://127.0.0.1:${downstreamPort}/vision`);
  assert.equal(proxied.statusCode, 200);
  assert.match(proxied.contentType, /multipart\/x-mixed-replace/);
  assert.equal(proxied.body.includes(Buffer.from('vision')), true);

  firstSocket.terminate();
  await waitFor(() => connections >= 2);

  client.stop();
  upstreamWs.close();
  await closeServer(downstream);
  await closeServer(upstreamHttp);
  console.log('PASS remote XVisio client proxies fixed streams and validates selection');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
