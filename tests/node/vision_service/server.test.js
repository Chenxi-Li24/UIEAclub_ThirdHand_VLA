'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { WebSocket } = require('ws');

const { createVisionService } = require(
  '../../../services/vision/src/server',
);

class FakeCamera {
  constructor() {
    this.started = false;
    this.clients = new Set();
    this.commands = [];
    this.selection = { stableId: null, requestId: null };
  }

  start() {
    this.started = true;
  }

  status() {
    return {
      camera: { status: this.started ? 'ready' : 'stopped', sequence: 1 },
      inference: { status: 'error', error: 'checkpoint missing' },
      selection: { ...this.selection },
    };
  }

  observation(stableId = null) {
    const targets = [{ stableId: 2, label: 'bottle', depthM: 0.42 }];
    const target = stableId === null
      ? null : targets.find(item => item.stableId === stableId);
    if (stableId !== null && !target) return null;
    return {
      schema: 'thirdhand.vision-observation.v1',
      frameId: 7,
      selectedStableId: 2,
      target,
      targets,
      robotControlEnabled: false,
    };
  }

  subscribe(kind, response) {
    if (kind !== 'raw') return false;
    this.clients.add(response);
    response.write(
      '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\n' +
      'jpeg\r\n',
    );
    return true;
  }

  unsubscribe(_kind, response) {
    this.clients.delete(response);
  }

  send(message) {
    this.commands.push(message);
    return true;
  }

  close() {
    for (const response of this.clients) response.end();
    this.clients.clear();
  }
}

test('raw MJPEG stays available when inference reports model error', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-vision-'));
  const readyFile = path.join(runtime, 'vision.ready');
  const camera = new FakeCamera();
  const service = createVisionService({
    host: '127.0.0.1',
    port: 0,
    readyFile,
    camera,
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await service.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const health = await fetch(`${origin}/health`).then(response => response.json());
  assert.equal(health.camera.status, 'ready');
  assert.equal(health.inference.status, 'error');
  assert.equal(fs.existsSync(readyFile), true);

  const raw = await fetch(`${origin}/camera/xvisio/raw`);
  assert.equal(raw.status, 200);
  assert.match(raw.headers.get('content-type'), /multipart\/x-mixed-replace/);
  await raw.body.cancel();

  const vision = await fetch(`${origin}/camera/xvisio/vision`);
  assert.equal(vision.status, 503);
  assert.equal((await vision.json()).code, 'inference_unavailable');

  const observation = await fetch(`${origin}/api/vision/observation`)
    .then(response => response.json());
  assert.equal(observation.selectedStableId, 2);
  assert.equal(observation.targets[0].depthM, 0.42);

  const target = await fetch(`${origin}/api/vision/targets/2`)
    .then(response => response.json());
  assert.equal(target.target.stableId, 2);

  const selected = await fetch(`${origin}/api/vision/select`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2, requestId: 'select-2' }),
  }).then(response => response.json());
  assert.equal(selected.requestId, 'select-2');
  assert.deepEqual(camera.commands.at(-1), {
    type: 'select_target', stableId: 2, requestId: 'select-2',
  });

  camera.commands.length = 0;
  camera.selection = { stableId: 1, requestId: 'select-1' };
  const switched = await fetch(`${origin}/api/vision/select`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ stableId: 2, requestId: 'select-2b' }),
  }).then(response => response.json());
  assert.equal(switched.accepted, true);
  assert.deepEqual(camera.commands, [
    { type: 'release_target', requestId: 'select-1' },
    { type: 'select_target', stableId: 2, requestId: 'select-2b' },
  ]);
});

test('person-follow aliases expose read-only status and observation', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-follow-'));
  const camera = new FakeCamera();
  const service = createVisionService({
    host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'vision.ready'), camera,
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const origin = `http://127.0.0.1:${address.port}`;
  const status = await fetch(`${origin}/api/vision/person-follow/status`).then(r => r.json());
  assert.equal(status.robotControlEnabled, false);
  assert.equal(status.serviceId, 'vision');
  const observation = await fetch(`${origin}/api/vision/person-follow/observation`).then(r => r.json());
  assert.equal(observation.robotControlEnabled, false);
  assert.equal(observation.selectedStableId, 2);
});

test('vision websocket forwards validated arm state without robot control', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-arm-state-'));
  const camera = new FakeCamera();
  const service = createVisionService({
    host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'vision.ready'), camera,
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(() => socket.close());
  await new Promise((resolve, reject) => {
    socket.once('open', resolve);
    socket.once('error', reject);
  });
  const state = {
    type: 'arm_state', pose_frame: 'robot_flange',
    connected: true, healthy: true, stationary: true,
    flange_position_m: [0.1275, 0, 0.17605],
    flange_euler_rad: [0, 0, 0], joints_deg: [0, 0, 0, 0, 0, 0],
    observed_monotonic_ns: 123,
  };
  socket.send(JSON.stringify(state));
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.deepEqual(camera.commands.at(-1), state);
});
