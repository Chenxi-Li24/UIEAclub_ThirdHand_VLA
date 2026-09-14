'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  loadAsrV2RuntimePolicy,
  startLocalBridges,
} = require('../asr-v2-runtime-policy');

test('copied runtime keeps every local hardware bridge disabled by default', () => {
  assert.deepEqual(loadAsrV2RuntimePolicy({}), {
    localRobotBridgeEnabled: false,
    localCameraBridgeEnabled: false,
  });
});

test('only the exact explicit opt-in value enables a local hardware bridge', () => {
  assert.deepEqual(loadAsrV2RuntimePolicy({
    LOCAL_ROBOT_BRIDGE_ENABLED: 'true',
    LOCAL_CAMERA_BRIDGE_ENABLED: 'yes',
  }), {
    localRobotBridgeEnabled: false,
    localCameraBridgeEnabled: false,
  });

  assert.deepEqual(loadAsrV2RuntimePolicy({
    LOCAL_ROBOT_BRIDGE_ENABLED: '1',
    LOCAL_CAMERA_BRIDGE_ENABLED: '1',
  }), {
    localRobotBridgeEnabled: true,
    localCameraBridgeEnabled: true,
  });
});

test('disabled policy never starts a copied robot or camera child', () => {
  const starts = [];
  const result = startLocalBridges(
    loadAsrV2RuntimePolicy({}),
    {
      robot: { start: () => starts.push('robot') },
      camera: { start: () => starts.push('camera') },
    },
  );

  assert.deepEqual(starts, []);
  assert.deepEqual(result, { robotStarted: false, cameraStarted: false });
});

test('explicit policy starts only the selected local child', () => {
  const starts = [];
  const result = startLocalBridges(
    loadAsrV2RuntimePolicy({ LOCAL_CAMERA_BRIDGE_ENABLED: '1' }),
    {
      robot: { start: () => starts.push('robot') },
      camera: { start: () => starts.push('camera') },
    },
  );

  assert.deepEqual(starts, ['camera']);
  assert.deepEqual(result, { robotStarted: false, cameraStarted: true });
});
