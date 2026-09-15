'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { once } = require('node:events');
const { WebSocket, WebSocketServer } = require('ws');

const { createWebGateway } = require('../../../apps/web/src/server');

const VOICE_PROTOCOL = 'thirdhand.voice.v1';

async function createVoiceStub() {
  const received = [];
  const server = http.createServer();
  const wss = new WebSocketServer({
    server,
    handleProtocols(protocols) {
      return protocols.has(VOICE_PROTOCOL) ? VOICE_PROTOCOL : false;
    },
  });
  wss.on('connection', socket => {
    assert.equal(socket.protocol, VOICE_PROTOCOL);
    socket.on('message', data => {
      const message = JSON.parse(data.toString('utf8'));
      received.push(message);
      socket.send(JSON.stringify({
        v: 1,
        type: 'model.catalog',
        messageId: 'catalog-1',
        replyTo: message.messageId,
        sessionId: null,
        ts: Date.now(),
        payload: { models: [] },
      }));
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    received,
    url: `ws://127.0.0.1:${server.address().port}/v1/voice`,
    async close() {
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

test('voice proxy preserves subprotocol, messages, and runtime config', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-voice-proxy-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(publicDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand</h1>');

  const voice = await createVoiceStub();
  const gateway = createWebGateway({
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: 'ws://127.0.0.1:9/ws',
    voiceWsUrl: voice.url,
  });
  t.after(async () => {
    await gateway.close();
    await voice.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const runtimeConfig = await fetch(`${origin}/api/runtime-config`)
    .then(response => response.json());
  assert.equal(runtimeConfig.voice.endpoint, '/voice');

  const browser = new WebSocket(
    `ws://127.0.0.1:${address.port}/voice`,
    VOICE_PROTOCOL,
  );
  await once(browser, 'open');
  t.after(() => browser.terminate());
  assert.equal(browser.protocol, VOICE_PROTOCOL);

  const replyPromise = once(browser, 'message');
  browser.send(JSON.stringify({
    v: 1,
    type: 'model.list',
    messageId: 'list-1',
    replyTo: null,
    sessionId: null,
    ts: Date.now(),
    payload: {},
  }));
  const [reply] = await replyPromise;
  assert.equal(JSON.parse(reply.toString('utf8')).type, 'model.catalog');
  assert.equal(voice.received[0].type, 'model.list');
});
test('formal Ubuntu voice UI uses three local models and same-origin routing', () => {
  const root = path.resolve(__dirname, '../../..');
  const index = fs.readFileSync(
    path.join(root, 'apps/web/public/index.html'),
    'utf8',
  );
  const voiceControl = fs.readFileSync(
    path.join(root, 'apps/web/public/js/voice-control.js'),
    'utf8',
  );

  for (const modelId of [
    'whisper-small',
    'paraformer-streaming',
    'fun-asr-nano',
  ]) {
    assert.match(index, new RegExp(`data-model-id="${modelId}"`));
  }
  assert.match(index, /Ubuntu PC 本地 AI/);
  assert.match(index, /voice-speaker-select/);
  assert.doesNotMatch(index, /Jetson 本地 AI|data-voice-port="300[12]"/);
  assert.match(voiceControl, /runtimeConfig\?\.voice\?\.endpoint/);
  assert.doesNotMatch(voiceControl, /:300[12]\//);
  assert.equal(
    fs.existsSync(path.join(root, 'apps/web/public/js/tts-player.js')),
    true,
  );

  const { voiceEndpoint } = require(
    '../../../apps/web/public/js/runtime-endpoints',
  );
  assert.equal(
    voiceEndpoint({ protocol: 'http:', host: '192.168.58.68:9983' }),
    'ws://192.168.58.68:9983/voice',
  );
});
