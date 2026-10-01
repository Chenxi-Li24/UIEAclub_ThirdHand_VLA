'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

const { CameraProcess } = require(
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

test('camera process forwards only validated flange state to projection bridge', () => {
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
