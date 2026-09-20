'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { loadConfig } = require('../../../services/robot/src/config');

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
