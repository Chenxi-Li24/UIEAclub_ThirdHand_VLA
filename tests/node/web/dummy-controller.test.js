'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { DummyController } = require('../../../apps/web/src/dummy-controller');
const { loadConfig } = require('../../../apps/web/src/config');

function harness(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dummy-control-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const config = loadConfig({});
  config.dummy.root = root;
  config.dummy.logFile = path.join(root, 'dummy.log');
  const child = new EventEmitter();
  child.pid = 1234;
  const signals = [];
  child.kill = signal => { signals.push(signal); return true; };
  const launches = [];
  const h = { observation: null, frame: null, vision: { status: 'ready' },
    robot: { connected: true, stateReady: true, moving: false, lastStateAt: Date.now(),
      continuousFollow: { j1MaxSpeedDegS: 50, j4MaxSpeedDegS: 50 } } };
  const controller = new DummyController(config, {
    platform: 'linux', exists: () => true,
    spawn: (...args) => { launches.push(args); return child; },
    fetchJson: async url => {
      if (url.endsWith('/api/status')) return h.observation;
      if (url.endsWith('/api/frame')) return h.frame;
      if (url.includes(':3000')) return { robot: h.robot };
      return h.vision;
    },
  });
  return { ...h, h, controller, config, child, signals, launches };
}
const start = c => c.start({ authorized: true, keywords: true });

test('Dummy starts only with explicit authorization and fixed command/resource args', async t => {
  const h = harness(t);
  await assert.rejects(h.controller.start({ authorized: false, keywords: true }), /authorization/);
  assert.equal(h.launches.length, 0);
  const result = await h.controller.start({ authorized: true, keywords: false });
  assert.equal(result.phase, 'starting');
  const [python, args, options] = h.launches[0];
  assert.equal(python, h.config.dummy.python);
  assert.equal(args[0], h.config.dummy.entry);
  assert.ok(args.includes('--enable-motion') && args.includes('--no-keywords'));
  assert.equal(options.shell, false);
  assert.equal(options.env.DUMMY_VISION_HTTP_URL, h.config.visionHttpUrl);
  assert.equal(options.env.DUMMY_URDF_PATH, h.config.dummy.urdf);
  await assert.rejects(start(h.controller), /already_running/);
});

test('Dummy rejects disconnected, stale, future, missing, busy or old backend state', async t => {
  const bad = [
    [{ connected: false }, /not_ready/], [{ stateReady: false }, /not_ready/],
    [{ lastStateAt: Date.now() - 2000 }, /not_ready/], [{ lastStateAt: Date.now() + 2000 }, /not_ready/],
    [{ lastStateAt: undefined }, /not_ready/], [{ moving: true }, /busy/],
    [{ continuousFollow: { j1MaxSpeedDegS: 15 } }, /upgrade_required/],
  ];
  for (const [patch, error] of bad) {
    const h = harness(t);
    Object.assign(h.h.robot, patch);
    await assert.rejects(start(h.controller), error);
    assert.equal(h.launches.length, 0);
  }
});

test('Dummy requires resources and ready Vision, never takes over external Dummy', async t => {
  const h = harness(t);
  h.controller.exists = () => false;
  await assert.rejects(start(h.controller), /python_missing/);
  h.controller.exists = () => true;
  h.h.vision = { status: 'degraded' };
  await assert.rejects(start(h.controller), /vision_not_ready/);
  h.h.observation = { schema: 'thirdhand-dummy-live-observation-v1', pid: 999 };
  await assert.rejects(start(h.controller), /external_process/);
  assert.equal((await h.controller.status()).phase, 'external');
  h.controller.stop();
  assert.equal(h.signals.length, 0);
  assert.equal(h.launches.length, 0);
});

test('Stop targets only owned child and waits for exit, frame requires matching owner', async t => {
  const h = harness(t);
  await start(h.controller);
  h.h.observation = { schema: 'thirdhand-dummy-live-observation-v1', pid: h.child.pid,
    project_root: h.config.dummy.root, frame_id: 8 };
  h.h.frame = { state: h.h.observation, jpeg_base64: 'jpeg' };
  assert.equal((await h.controller.status()).phase, 'running');
  assert.equal((await h.controller.frame()).jpeg_base64, 'jpeg');
  h.h.frame = { state: { pid: 999 }, jpeg_base64: 'other' };
  await assert.rejects(h.controller.frame(), /owner_mismatch/);
  assert.equal(h.controller.stop().phase, 'stopping');
  h.controller.stop();
  assert.deepEqual(h.signals, ['SIGTERM']);
  let closed = false;
  const closing = h.controller.close().then(() => { closed = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(closed, false);
  h.child.emit('exit', 0, null);
  h.h.observation = null;
  await closing;
  assert.equal((await h.controller.status()).phase, 'stopped');
  await assert.rejects(start(h.controller), /closed/);
});

test('Unexpected process exit is failed, not a successful hold', async t => {
  const h = harness(t);
  await start(h.controller);
  h.child.emit('exit', 2, null);
  assert.equal((await h.controller.status()).phase, 'failed');
  assert.equal((await h.controller.status()).reason, 'dummy_exit_2');
  await assert.rejects(h.controller.frame(), /not_running/);
});

test('Concurrent starts are rejected and close during preflight never launches motion', async t => {
  const h = harness(t);
  let resolve;
  h.controller.observation = () => new Promise(done => { resolve = done; });
  const pending = start(h.controller);
  await assert.rejects(start(h.controller), /already_running/);
  const closing = h.controller.close();
  resolve(null);
  await assert.rejects(pending, /closed/);
  await closing;
  assert.equal(h.launches.length, 0);
});

test('Web config derives transcript service and refuses zero managed telemetry port', () => {
  assert.equal(loadConfig({ VOICE_WS_URL: 'ws://localhost:3005/v1/voice' }).dummy.speechWs,
    'ws://localhost:3005/v1/transcripts');
  assert.throws(() => loadConfig({ DUMMY_TELEMETRY_PORT: '0' }), /must not be zero/);
});
