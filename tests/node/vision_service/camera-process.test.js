'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { CameraProcess, buildBridgeArgs } = require(
  '../../../services/vision/src/camera-process',
);

class FakeResponse extends EventEmitter {
  constructor() {
    super();
    this.destroyed = false;
    this.writableEnded = false;
  }

  write() {
    return true;
  }

  end() {
    this.writableEnded = true;
  }
}

test('camera process enables only streams with active HTTP subscribers', () => {
  const messages = [];
  const camera = new CameraProcess({ restartDelayMs: 2000 });
  camera.child = {
    stdin: {
      writable: true,
      destroyed: false,
      write(line) {
        messages.push(JSON.parse(line));
        return true;
      },
    },
  };
  const first = new FakeResponse();
  const second = new FakeResponse();

  assert.equal(camera.subscribe('raw', first), true);
  assert.equal(camera.subscribe('raw', second), true);
  assert.deepEqual(messages, [
    { type: 'set_stream_enabled', kind: 'raw', enabled: true },
  ]);

  assert.equal(camera.unsubscribe('raw', first), true);
  assert.equal(messages.length, 1);
  assert.equal(camera.unsubscribe('raw', second), true);
  assert.deepEqual(messages[1], {
    type: 'set_stream_enabled',
    kind: 'raw',
    enabled: false,
  });
});

test('camera process preserves deployed handeye and URDF bridge arguments', () => {
  assert.deepEqual(buildBridgeArgs({
    bridgeScript: '/bridge.py',
    visionConfig: '/vision.yaml',
    xvisioExecutable: '/xvisio',
    handeye: '/handeye.json',
    robotUrdf: '/robot.urdf',
  }), [
    '-u', '/bridge.py', '--config', '/vision.yaml',
    '--executable', '/xvisio',
    '--handeye', '/handeye.json', '--urdf', '/robot.urdf',
  ]);
});

test('camera process forwards only validated flange state to projection bridge', () => {
  const messages = [];
  const camera = new CameraProcess({ restartDelayMs: 2000 });
  attachWritableChild(camera, messages);
  const state = {
    type: 'arm_state', pose_frame: 'robot_flange',
    connected: true, healthy: true, stationary: true,
    flange_position_m: [0.1275, 0, 0.17605],
    flange_euler_rad: [0, 0, 0], joints_deg: [0, 0, 0, 0, 0, 0],
    observed_monotonic_ns: 123,
  };
  assert.equal(camera.send(state), true);
  assert.deepEqual(messages, [state]);
  assert.equal(camera.send({ ...state, pose_frame: 'tool' }), false);
});

function attachWritableChild(camera, messages) {
  camera.child = {
    stdin: {
      writable: true,
      destroyed: false,
      write(line) {
        messages.push(JSON.parse(line));
        return true;
      },
    },
  };
}

test('camera process resolves one selected-target export and rejects concurrency', async () => {
  const messages = [];
  const camera = new CameraProcess({ exportTimeoutMs: 1000 });
  attachWritableChild(camera, messages);

  const first = camera.exportSelectedTarget();
  await assert.rejects(
    camera.exportSelectedTarget(),
    error => error.code === 'export_in_progress' && error.statusCode === 409,
  );
  assert.equal(messages.length, 1);
  assert.equal(messages[0].type, 'export_selected_target');

  camera._handleEvent(JSON.stringify({
    type: 'selected_target_export_result',
    requestId: messages[0].requestId,
    ok: true,
    path: '/tmp/selected.npz',
    schema: 'thirdhand-selected-target-bundle-v1',
    frame_id: 42,
    length_unit: 'm',
    point_frame: 'xvisio_color',
  }));
  const result = await first;
  assert.equal(result.path, '/tmp/selected.npz');
  assert.equal(result.metadata.frame_id, 42);
});

test('camera process times out and removes a late temporary export', async () => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-export-timeout-'));
  const lateBundle = path.join(runtime, 'late.npz');
  const messages = [];
  const camera = new CameraProcess({ exportTimeoutMs: 15 });
  attachWritableChild(camera, messages);
  try {
    const pending = camera.exportSelectedTarget();
    await assert.rejects(
      pending,
      error => error.code === 'export_timeout' && error.statusCode === 504,
    );
    fs.writeFileSync(lateBundle, 'late');
    camera._handleEvent(JSON.stringify({
      type: 'selected_target_export_result',
      requestId: messages[0].requestId,
      ok: true,
      path: lateBundle,
      schema: 'thirdhand-selected-target-bundle-v1',
      frame_id: 43,
      length_unit: 'm',
      point_frame: 'xvisio_color',
    }));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(fs.existsSync(lateBundle), false);
  } finally {
    fs.rmSync(runtime, { recursive: true, force: true });
  }
});
