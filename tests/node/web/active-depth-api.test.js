'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const http = require('node:http');
const { WebSocketServer } = require('ws');
const { createWebGateway } = require('../../../apps/web/src/server');
const { ActiveDepthCoordinator } = require('../../../apps/web/src/active-depth/coordinator');
const { ExecutionClient } = require('../../../apps/web/src/active-depth/execution-client');
const { VisionClient } = require('../../../apps/web/src/active-depth/vision-client');

class FakeCoordinator extends EventEmitter {
  constructor() {
    super();
    this.current = { type: 'active_depth.status', phase: 'idle', active: false, sessionId: null };
    this.closed = false;
  }
  status() { return this.current; }
  async start(stableId) {
    if (this.current.active) throw Object.assign(new Error('active'), { code: 'active_depth_active' });
    this.current = {
      type: 'active_depth.status', phase: 'observing', active: true,
      sessionId: 'session-1', stableId,
    };
    this.emit('status', this.current);
    return this.current;
  }
  async stop(sessionId) {
    this.current = { ...this.current, phase: 'stopped', active: false, reason: 'operator_stop', sessionId };
    this.emit('status', this.current);
    return this.current;
  }
  async close() { this.closed = true; }
}

function fakeProxy() {
  return {
    broadcasts: [], attached: 0, closed: false,
    attach() { this.attached += 1; },
    broadcast(message) { this.broadcasts.push(message); },
    getRobotState() { return { stateName: 'IDLE', jointsDeg: [0,0,0,0,0,0] }; },
    close() { this.closed = true; },
  };
}

async function gatewayHarness(t) {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'active-depth-api-'));
  const publicDir = path.join(runtime, 'public');
  fs.mkdirSync(publicDir);
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>test</h1>');
  const coordinator = new FakeCoordinator();
  const robotProxy = fakeProxy();
  const gateway = createWebGateway({
    host: '127.0.0.1', port: 0, publicDir, assetsDir: runtime,
    readyFile: path.join(runtime, 'web.ready'), coordinator, robotProxy,
    visionProxy: fakeProxy(), voiceProxy: fakeProxy(),
  });
  const address = await gateway.start();
  t.after(async () => { await gateway.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  return { origin: `http://127.0.0.1:${address.port}`, coordinator, robotProxy };
}

test('active-depth API starts explicitly, reads status, and stops idempotently', async (t) => {
  const h = await gatewayHarness(t);
  const started = await fetch(`${h.origin}/api/active-depth/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2 }),
  });
  assert.equal(started.status, 202);
  assert.equal((await started.json()).stableId, 2);

  const duplicate = await fetch(`${h.origin}/api/active-depth/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2 }),
  });
  assert.equal(duplicate.status, 409);

  const status = await fetch(`${h.origin}/api/active-depth/status`);
  assert.equal((await status.json()).sessionId, 'session-1');
  const stopped = await fetch(`${h.origin}/api/active-depth/stop`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ sessionId: 'session-1' }),
  });
  assert.equal(stopped.status, 200);
  assert.equal((await stopped.json()).phase, 'stopped');
  assert.ok(h.robotProxy.broadcasts.some(message => message.phase === 'stopped'));
});

test('active-depth API rejects unknown keys, invalid IDs, and oversized bodies', async (t) => {
  const h = await gatewayHarness(t);
  for (const body of [{ stableId: 0 }, { stableId: 2, extra: true }]) {
    const response = await fetch(`${h.origin}/api/active-depth/start`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body),
    });
    assert.equal(response.status, 400);
  }
  const oversized = await fetch(`${h.origin}/api/active-depth/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2, padding: 'x'.repeat(17 * 1024) }),
  });
  assert.equal(oversized.status, 413);
  assert.doesNotMatch(await oversized.text(), /robot-execution|token/i);
});

test('runtime responses expose readiness but never execution secrets', async (t) => {
  const h = await gatewayHarness(t);
  for (const route of ['/health', '/api/runtime-config', '/api/active-depth/status']) {
    const response = await fetch(`${h.origin}${route}`);
    const text = await response.text();
    assert.equal(response.status, 200);
    assert.doesNotMatch(text, /ROBOT_EXECUTION_TOKEN|private\.token|c{64}/);
  }
});

test('browser websocket reconnect receives current server-owned session', async (t) => {
  const h = await gatewayHarness(t);
  await fetch(`${h.origin}/api/active-depth/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2 }),
  });
  const socket = new WebSocket(h.origin.replace('http:', 'ws:') + '/ws');
  t.after(() => socket.close());
  const message = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('message timeout')), 500);
    socket.addEventListener('message', event => {
      clearTimeout(timer);
      resolve(JSON.parse(String(event.data)));
    }, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  assert.equal(message.type, 'active_depth.status');
  assert.equal(message.sessionId, 'session-1');
});

test('simulated end-to-end alignment reaches depth without any gripper command', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'active-depth-e2e-'));
  const tokenFile = path.join(runtime, 'token');
  fs.writeFileSync(tokenFile, `${'d'.repeat(64)}\n`, { mode: 0o600 });
  const primitives = [];
  const executionHttp = http.createServer();
  const executionWs = new WebSocketServer({ noServer: true });
  executionHttp.on('upgrade', (request, socket, head) => {
    assert.equal(request.headers['x-thirdhand-execution-token'], 'd'.repeat(64));
    executionWs.handleUpgrade(request, socket, head, ws => executionWs.emit('connection', ws));
  });
  executionWs.on('connection', socket => socket.on('message', data => {
    const message = JSON.parse(data.toString('utf8'));
    if (message.type === 'execution.stop') return;
    primitives.push(message);
    socket.send(JSON.stringify({ type: 'execution.status', status: 'accepted', primitiveId: message.primitiveId }));
    socket.send(JSON.stringify({ type: 'execution.status', status: 'completed', code: 'target_reached', primitiveId: message.primitiveId }));
  }));
  await new Promise(resolve => executionHttp.listen(0, '127.0.0.1', resolve));

  const frames = [
    { id: 1, pixel: [520,310], depth: false }, { id: 2, pixel: [460,285], depth: false },
    { id: 3, pixel: [320,236], depth: true }, { id: 4, pixel: [318,235], depth: true },
    { id: 5, pixel: [316,234], depth: true },
  ];
  let currentFrame = frames[0];
  const detectionFor = next => ({
    frame_id: next.id, ts: Date.now(), selected_stable_id: 2,
    evidence_id: `sha256:${String(next.id).padStart(64, '0')}`, motion_epoch: 0,
    targets: [{ stable_id: 2, centroid_xy: next.pixel, track_state: 'confirmed',
      depth_valid: next.depth, camera_xyz_m: next.depth ? [0,0,0.4] : null }],
  });
  const visionHttp = http.createServer((request, response) => {
    response.setHeader('content-type', 'application/json');
    if (request.url === '/api/vision/status') {
      response.end(JSON.stringify({
        runtimeEvidence: { camera_mount_id: 'mount-1', registration_id: 'registration-1' },
        detection: detectionFor(currentFrame),
      }));
      return;
    }
    const next = frames.shift();
    currentFrame = next;
    response.end(JSON.stringify({
      frameId: next.id, observedAtMs: Date.now(), selectedStableId: 2,
      evidence_id: `sha256:${String(next.id).padStart(64, '0')}`, motion_epoch: 0,
      robotControlEnabled: false,
      targets: [{ stable_id: 2, centroid_xy: next.pixel, track_state: 'confirmed',
        depth_valid: next.depth, camera_xyz_m: next.depth ? [0,0,0.4] : null }],
    }));
  });
  await new Promise(resolve => visionHttp.listen(0, '127.0.0.1', resolve));

  const plans = [
    { ok: true, tier: 'wrist', wristExhausted: false, targetJointsDeg: [0,0,0,0,1,0],
      predictedPixel: [460,285], jointDeltasDeg: [0,0,0,0,1,0], cameraShiftM: 0 },
    { ok: true, tier: 'arm_fallback', wristExhausted: true, targetJointsDeg: [0.5,0,0,0,0,0],
      predictedPixel: [410,265], jointDeltasDeg: [0.5,0,0,0,0,0], cameraShiftM: 0 },
  ];
  const executionClient = new ExecutionClient({
    endpoint: `ws://127.0.0.1:${executionHttp.address().port}/execution`, tokenFile,
  });
  const coordinator = new ActiveDepthCoordinator({
    executionClient,
    visionClient: new VisionClient({ baseUrl: `http://127.0.0.1:${visionHttp.address().port}` }),
    getRobotState: () => ({ stateName: 'IDLE', motionActive: false,
      jointsDeg: [0,0,0,0,0,0], observedAtMs: Date.now() }),
    mount: { matrix_4x4: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
      camera_mount_id: 'mount-1', registration_id: 'registration-1' },
    pollIntervalMs: 0,
    planStep: () => plans.shift() || { ok: false, reason: 'unexpected_plan' },
  });
  const publicDir = path.join(runtime, 'public');
  fs.mkdirSync(publicDir);
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>test</h1>');
  const gateway = createWebGateway({
    host: '127.0.0.1', port: 0, publicDir, assetsDir: runtime,
    readyFile: path.join(runtime, 'web.ready'), coordinator,
    robotProxy: fakeProxy(), visionProxy: fakeProxy(), voiceProxy: fakeProxy(),
  });
  const address = await gateway.start();
  t.after(async () => {
    await gateway.close();
    for (const client of executionWs.clients) client.terminate();
    await new Promise(resolve => executionWs.close(resolve));
    await new Promise(resolve => executionHttp.close(resolve));
    await new Promise(resolve => visionHttp.close(resolve));
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const origin = `http://127.0.0.1:${address.port}`;
  const started = await fetch(`${origin}/api/active-depth/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ stableId: 2 }),
  });
  assert.equal(started.status, 202);
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const status = await fetch(`${origin}/api/active-depth/status`).then(response => response.json());
    if (status.phase === 'depth_acquired') break;
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  const terminal = await fetch(`${origin}/api/active-depth/status`).then(response => response.json());
  assert.equal(terminal.phase, 'depth_acquired');
  assert.deepEqual(primitives.map(item => item.parameters.tier), ['wrist', 'arm_fallback']);
  assert.equal(primitives.some(item => item.operation === 'gripper.set'), false);
  assert.doesNotMatch(JSON.stringify(terminal), /d{64}/);
});
