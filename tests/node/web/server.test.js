'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');

const { createWebGateway } = require('../../../apps/web/src/server');

function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const check = () => {
      if (predicate()) return resolve();
      if (Date.now() >= deadline) return reject(new Error('condition timeout'));
      setTimeout(check, 10);
    };
    check();
  });
}

function inbox(socket) {
  const messages = [];
  const waiters = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(String(event.data));
    const waiterIndex = waiters.findIndex(item => item.predicate(message));
    if (waiterIndex >= 0) {
      const [waiter] = waiters.splice(waiterIndex, 1);
      clearTimeout(waiter.timer);
      waiter.resolve(message);
      return;
    }
    messages.push(message);
  });
  return predicate => {
    const index = messages.findIndex(predicate);
    if (index >= 0) return Promise.resolve(messages.splice(index, 1)[0]);
    return new Promise((resolve, reject) => {
      const waiter = { predicate, resolve, reject };
      waiter.timer = setTimeout(() => {
        const position = waiters.indexOf(waiter);
        if (position >= 0) waiters.splice(position, 1);
        reject(new Error('message timeout'));
      }, 3000);
      waiters.push(waiter);
    });
  };
}

async function createRobotStub() {
  const received = [];
  const server = http.createServer();
  const wss = new WebSocketServer({ server });
  wss.on('connection', socket => {
    socket.send(JSON.stringify({
      type: 'config',
      connection: { connected: false, mode: 'startouch' },
    }));
    socket.on('message', data => received.push(JSON.parse(data.toString('utf8'))));
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    received,
    url: `ws://127.0.0.1:${server.address().port}/ws`,
    async close() {
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

async function createPlanStub() {
  const received = [];
  const server = http.createServer();
  const wss = new WebSocketServer({
    server,
    handleProtocols(protocols) {
      return protocols.has('thirdhand.plan.v1') ? 'thirdhand.plan.v1' : false;
    },
  });
  wss.on('connection', socket => {
    assert.equal(socket.protocol, 'thirdhand.plan.v1');
    socket.on('message', data => {
      const message = JSON.parse(data.toString('utf8'));
      received.push(message);
      socket.send(JSON.stringify({ type: 'plan.proposed', proposal: { proposalId: 'proposal-1' } }));
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    received,
    url: `ws://127.0.0.1:${server.address().port}/plan`,
    async close() {
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

test('web gateway serves UI and proxies only robot commands', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-web-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(path.join(assetsDir, 'startouch-v3'), { recursive: true });
  fs.mkdirSync(publicDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand Control</h1>');
  fs.writeFileSync(path.join(publicDir, 'plan-channel.mjs'), 'export const ready = true;');
  fs.writeFileSync(path.join(assetsDir, 'startouch-v3', 'model.urdf'), '<robot/>');

  const robot = await createRobotStub();
  const gateway = createWebGateway({
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: robot.url,
    visionHttpUrl: 'http://127.0.0.1:1',
  });
  t.after(async () => {
    await gateway.close();
    await robot.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const page = await fetch(`${origin}/`);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /ThirdHand Control/);

  const moduleResponse = await fetch(`${origin}/plan-channel.mjs`);
  assert.equal(moduleResponse.status, 200);
  assert.match(moduleResponse.headers.get('content-type'), /^text\/javascript\b/);

  const model = await fetch(`${origin}/models/startouch-v3/model.urdf`);
  assert.equal(model.status, 200);
  assert.equal(await model.text(), '<robot/>');

  const health = await fetch(`${origin}/health`).then(response => response.json());
  assert.equal(health.status, 'ready');
  assert.equal(health.dependencies.robot.url, robot.url);
  assert.equal(fs.existsSync(readyFile), true);

  const traversal = await fetch(`${origin}/%2e%2e/package.json`);
  assert.ok([403, 404].includes(traversal.status));

  const vision = await fetch(`${origin}/api/vision/status`);
  assert.equal(vision.status, 503);
  assert.equal((await vision.json()).code, 'vision_upstream_unavailable');

  const browser = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  const next = inbox(browser);
  await new Promise((resolve, reject) => {
    browser.addEventListener('open', resolve, { once: true });
    browser.addEventListener('error', reject, { once: true });
  });
  t.after(() => browser.close());

  const config = await next(message => message.type === 'config');
  assert.equal(config.connection.mode, 'startouch');

  browser.send(JSON.stringify({ cmd: 'connect' }));
  await waitFor(() => robot.received.some(message => message.cmd === 'connect'));

  browser.send(JSON.stringify({ cmd: 'start_vision_grasp' }));
  const rejected = await next(message => message.type === 'error');
  assert.equal(rejected.code, 'service_unavailable');
  assert.equal(robot.received.some(message => message.cmd === 'start_vision_grasp'), false);
});

test('web gateway exposes an isolated Plan proxy with its required protocol', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-plan-proxy-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(publicDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand</h1>');

  const plan = await createPlanStub();
  const gateway = createWebGateway({
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: 'ws://127.0.0.1:9/ws',
    orchestratorWsUrl: plan.url,
  });
  t.after(async () => {
    await gateway.close();
    await plan.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const runtimeConfig = await fetch(`${origin}/api/runtime-config`).then(response => response.json());
  assert.deepEqual(runtimeConfig.plan, { endpoint: '/plan', protocol: 'thirdhand.plan.v1' });
  const health = await fetch(`${origin}/health`).then(response => response.json());
  assert.equal(health.dependencies.orchestrator.url, plan.url);

  const browser = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { browser.once('open', resolve); browser.once('error', reject); });
  t.after(() => browser.terminate());
  assert.equal(browser.protocol, 'thirdhand.plan.v1');
  const reply = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('plan reply timeout')), 2000);
    browser.once('message', data => { clearTimeout(timer); resolve(JSON.parse(data.toString('utf8'))); });
  });
  browser.send(JSON.stringify({ type: 'candidate.submit', candidate: { candidateId: 'candidate-1' } }));
  assert.equal((await reply).type, 'plan.proposed');
  assert.equal(plan.received[0].type, 'candidate.submit');

  const noProtocol = new WebSocket(`ws://127.0.0.1:${address.port}/plan`);
  const unexpected = await new Promise(resolve => {
    noProtocol.once('open', () => resolve('open'));
    noProtocol.once('unexpected-response', (_, response) => resolve(response.statusCode));
    noProtocol.once('error', () => resolve('error'));
  });
  assert.equal(unexpected, 426);
  assert.equal((await fetch(`${origin}/execution`)).status, 404);
});
