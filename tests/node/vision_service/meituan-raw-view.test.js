'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { CameraProcess } = require('../../../services/vision/src/camera-process');
const { createVisionService } = require('../../../services/vision/src/server');
const { createMeituanRawView } = require('../../../services/vision/src/meituan-raw-view');

class SharedCamera extends CameraProcess {
  constructor() {
    super({});
    this.starts = 0;
    this.commands = [];
    this.child = { stdin: {
      writable: true, destroyed: false,
      write: line => { this.commands.push(JSON.parse(line)); return true; }
    } };
    this._status.camera = { status: 'ready', sequence: 1, error: null };
    this._status.inference = { status: 'error', error: 'test inference unavailable' };
    this._status.selection = { stableId: 1, requestId: 'teammate-target' };
  }
  start() { this.starts += 1; }
  async close() { for (const stream of Object.values(this.streams)) stream.close(); }
  push(body) {
    this.streams.raw.push(Buffer.from(
      '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\n' + body + '\r\n'
    ));
  }
}

async function waitFor(predicate) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error('subscriber count did not converge');
    await new Promise(resolve => setTimeout(resolve, 10));
  }
}

test('3100 and Meituan receive the same raw frame from one camera owner', async t => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'meituan-shared-camera-'));
  const camera = new SharedCamera();
  const service = createVisionService({
    camera, host: '127.0.0.1', port: 0,
    meituanWorktree: path.resolve(__dirname, '../../..'),
    meituanHost: '127.0.0.1', meituanPort: 0,
    readyFile: path.join(runtime, 'vision.ready')
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const primary = await service.start();
  const secondary = service.meituanAddress();
  assert.ok(secondary);
  assert.equal(camera.starts, 1);

  const firstRequest = fetch('http://127.0.0.1:' + primary.port + '/camera/xvisio/raw');
  const secondRequest = fetch('http://127.0.0.1:' + secondary.port + '/camera/xvisio/raw');
  await waitFor(() => camera.streams.raw.subscriberCount() === 2);
  camera.push('AAAA');
  const [first, second] = await Promise.all([firstRequest, secondRequest]);
  assert.equal(first.status, 200);
  assert.equal(second.status, 200);
  const firstReader = first.body.getReader();
  const secondReader = second.body.getReader();
  const [a, b] = await Promise.all([firstReader.read(), secondReader.read()]);
  assert.deepEqual(a.value, b.value);
  assert.deepEqual(camera.commands, [
    { type: 'set_stream_enabled', kind: 'raw', enabled: true }
  ]);

  await secondReader.cancel();
  await waitFor(() => camera.streams.raw.subscriberCount() === 1);
  assert.equal(camera.commands.length, 1, 'closing Meituan must not disable the primary stream');
  camera.push('BBBB');
  const next = await firstReader.read();
  assert.match(Buffer.from(next.value).toString(), /BBBB/);
  assert.equal(camera.status().selection.requestId, 'teammate-target');
  await firstReader.cancel();
});

test('Meituan raw port is read-only and closing it does not own the camera lifecycle', async t => {
  const camera = new SharedCamera();
  const view = createMeituanRawView({ camera, host: '127.0.0.1', port: 0 });
  t.after(() => view.close());
  const address = await view.start();
  const origin = 'http://127.0.0.1:' + address.port;
  const health = await fetch(origin + '/health').then(response => response.json());
  assert.equal(health.serviceId, 'meituan-vision');
  assert.equal(health.mode, 'raw-only');
  assert.equal(health.camera.status, 'ready');
  assert.equal(health.batteryDetection.status, 'not_implemented');
  const pending = await fetch(origin + '/camera/xvisio/vision');
  assert.equal(pending.status, 501);
  assert.equal((await pending.json()).code, 'battery_detection_not_implemented');
  const rejected = await fetch(origin + '/api/vision/select', {
    method: 'POST', body: '{"stableId":2}'
  });
  assert.equal(rejected.status, 405);
  assert.equal(camera.starts, 0);
  assert.deepEqual(camera.commands, []);
  await view.close();
  assert.equal(camera.status().selection.stableId, 1);
});

test('occupied Meituan port does not take down the existing vision listener', async t => {
  const occupied = http.createServer();
  await new Promise(resolve => occupied.listen(0, '127.0.0.1', resolve));
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'meituan-port-conflict-'));
  const camera = new SharedCamera();
  const service = createVisionService({
    camera, host: '127.0.0.1', port: 0,
    meituanWorktree: path.resolve(__dirname, '../../..'),
    meituanHost: '127.0.0.1', meituanPort: occupied.address().port,
    readyFile: path.join(runtime, 'vision.ready')
  });
  t.after(async () => {
    await service.close();
    await new Promise(resolve => occupied.close(resolve));
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  assert.equal(service.meituanAddress(), null);
  const health = await fetch('http://127.0.0.1:' + address.port + '/health');
  assert.equal(health.status, 200);
  assert.equal(camera.starts, 1);
});
