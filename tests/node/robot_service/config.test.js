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
});
