'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');

const { createVisionService } = require(
  '../../../services/vision/src/server',
);

class FakeCamera {
  constructor() {
    this.started = false;
    this.clients = new Set();
    this.commands = [];
    this.selection = { stableId: null, requestId: null };
    this.exportResult = null;
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

  async exportSelectedTarget() {
    if (this.exportResult instanceof Error) throw this.exportResult;
    return this.exportResult;
  }

  async exportRawFrame() {
    if (this.rawExportResult instanceof Error) throw this.rawExportResult;
    return this.rawExportResult;
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

test('selected-target export returns NPZ with versioned frame metadata', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-export-http-'));
  const bundle = path.join(runtime, 'selected.npz');
  fs.writeFileSync(bundle, Buffer.from('NPZ-BUNDLE'));
  const camera = new FakeCamera();
  camera.exportResult = {
    path: bundle,
    metadata: {
      schema: 'thirdhand-selected-target-bundle-v1',
      frame_id: 42,
      length_unit: 'm',
      point_frame: 'xvisio_color',
    },
  };
  const service = createVisionService({
    host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'vision.ready'), camera,
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const response = await fetch(
    `http://127.0.0.1:${address.port}/api/vision/selected-target/export`,
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'application/x-npz');
  assert.equal(
    response.headers.get('x-thirdhand-schema'),
    'thirdhand-selected-target-bundle-v1',
  );
  assert.equal(response.headers.get('x-thirdhand-frame-id'), '42');
  assert.equal(response.headers.get('x-thirdhand-length-unit'), 'm');
  assert.equal(response.headers.get('x-thirdhand-point-frame'), 'xvisio_color');
  assert.equal(Buffer.from(await response.arrayBuffer()).toString(), 'NPZ-BUNDLE');
  const deadline = Date.now() + 1000;
  while (fs.existsSync(bundle) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.equal(fs.existsSync(bundle), false);
});

test('raw RGB-D export returns NPZ and removes temporary bundle', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-raw-http-'));
  const bundle = path.join(runtime, 'raw.npz');
  fs.writeFileSync(bundle, Buffer.from('RAW-NPZ'));
  const camera = new FakeCamera();
  camera.rawExportResult = { path: bundle, metadata: {
    schema: 'thirdhand-raw-rgbd-frame-v1', frame_id: 99,
    length_unit: 'm', point_frame: 'xvisio_color',
  }};
  const service = createVisionService({ host: '127.0.0.1', port: 0, camera });
  t.after(async () => { await service.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await service.start();
  const response = await fetch(`http://127.0.0.1:${address.port}/api/vision/raw-frame/export`);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('x-thirdhand-schema'), 'thirdhand-raw-rgbd-frame-v1');
  assert.equal(response.headers.get('x-thirdhand-frame-id'), '99');
  assert.equal(Buffer.from(await response.arrayBuffer()).toString(), 'RAW-NPZ');
  const deadline = Date.now() + 1000;
  while (fs.existsSync(bundle) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.equal(fs.existsSync(bundle), false);
});

test('selected-target export maps invalid and busy requests to explicit errors', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-export-errors-'));
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

  camera.exportResult = Object.assign(new Error('target lost'), {
    code: 'selected_target_lost', statusCode: 409,
  });
  let response = await fetch(`${origin}/api/vision/selected-target/export`);
  assert.equal(response.status, 409);
  assert.equal((await response.json()).code, 'selected_target_lost');

  camera.exportResult = Object.assign(new Error('export in progress'), {
    code: 'export_in_progress', statusCode: 409,
  });
  response = await fetch(`${origin}/api/vision/selected-target/export`);
  assert.equal(response.status, 409);
  assert.equal((await response.json()).code, 'export_in_progress');
});

test('selected-target export removes bundle after client disconnects', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-export-abort-'));
  const bundle = path.join(runtime, 'aborted.npz');
  let releaseExport;
  const camera = new FakeCamera();
  camera.exportSelectedTarget = () => new Promise(resolve => {
    releaseExport = resolve;
  });
  const service = createVisionService({
    host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'vision.ready'), camera,
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const request = http.get({
    host: '127.0.0.1', port: address.port,
    path: '/api/vision/selected-target/export',
  });
  request.on('error', () => {});
  while (!releaseExport) await new Promise(resolve => setImmediate(resolve));
  request.destroy();
  fs.writeFileSync(bundle, Buffer.from('NPZ-BUNDLE'));
  releaseExport({
    path: bundle,
    metadata: {
      schema: 'thirdhand-selected-target-bundle-v1', frame_id: 44,
      length_unit: 'm', point_frame: 'xvisio_color',
    },
  });
  const deadline = Date.now() + 1000;
  while (fs.existsSync(bundle) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 5));
  }
  assert.equal(fs.existsSync(bundle), false);
});
