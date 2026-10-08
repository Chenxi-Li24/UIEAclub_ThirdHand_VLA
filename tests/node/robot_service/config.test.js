'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { loadConfig } = require('../../../services/robot/src/config');
const { RobotController } = require('../../../services/robot/src/robot-controller');

test('robot config accepts a separate generated Python module path', () => {
  const config = loadConfig({
    ROBOT_PORT: '3000',
    STARTOUCH_SDK_PATH: '/project/local/sdk/startouch',
    STARTOUCH_MODULE_PATH: '/project/local/generated/startouch-python',
  });

  assert.equal(config.robot.sdkPath, '/project/local/sdk/startouch');
  assert.equal(
    config.robot.modulePath,
    '/project/local/generated/startouch-python',
  );
  assert.deepEqual(
    config.robot.homePresetDeg,
    [-0.163927, -2.611904, -4, 33.058620, 0.338783, 0.185784],
  );
  assert.deepEqual(config.robot.zeroPresetDeg, [0, 0, 0, 0, 0, 0]);
});

test('robot config allows explicit home and zero preset overrides', () => {
  const config = loadConfig({
    STARTOUCH_HOME_DEG: '1,2,3,4,5,6',
    STARTOUCH_ZERO_DEG: '6,5,4,3,2,1',
  });

  assert.deepEqual(config.robot.homePresetDeg, [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(config.robot.zeroPresetDeg, [6, 5, 4, 3, 2, 1]);
});

test('robot bridge errors preserve request id for command diagnostics', () => {
  const config = loadConfig({
    STARTOUCH_SIMULATE: '1',
    STARTOUCH_REQUIRE_CAN_RX: '0',
  });
  const controller = new RobotController(config.robot);
  let observed = null;
  controller.on('message', message => {
    if (message.type === 'error') observed = message;
  });

  controller.bridge.emit('bridge_error', {
    message: 'a joint motion is already active',
    request_id: 'req-motion-1',
    command: 'move_joint',
  });

  assert.equal(observed.code, 'bridge_error');
  assert.equal(observed.request_id, 'req-motion-1');
  assert.equal(observed.command, 'move_joint');
});
