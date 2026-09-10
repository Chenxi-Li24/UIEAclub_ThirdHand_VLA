'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

const modulePath = path.resolve(__dirname, '../../web/js/runtime-endpoints.js');
assert.equal(fs.existsSync(modulePath), true, 'runtime endpoint module must exist');
const { voiceEndpoint } = require(modulePath);

assert.equal(
  voiceEndpoint(3002, { protocol: 'http:', hostname: '192.168.58.68' }),
  'ws://192.168.58.68:3002/v1/voice'
);
assert.equal(
  voiceEndpoint(3001, { protocol: 'https:', hostname: 'robot.example' }),
  'wss://robot.example:3001/v1/voice'
);
assert.equal(
  voiceEndpoint(3002, { protocol: 'http:', hostname: '[::1]' }),
  'ws://[::1]:3002/v1/voice'
);
assert.throws(() => voiceEndpoint(0, { protocol: 'http:', hostname: 'localhost' }), /port/);

console.log('PASS voice endpoints follow the web-control host and transport');

const envExample = fs.readFileSync(
  path.resolve(__dirname, '../../.env.example'),
  'utf8'
);
const launcher = fs.readFileSync(
  path.resolve(__dirname, '../../scripts/start_ubuntu.sh'),
  'utf8'
);
for (const setting of [
  'XVISION_PROXY_ENABLED=1',
  'XVISION_SERVICE_URL=http://127.0.0.1:3100',
  'XVISION_WS_URL=ws://127.0.0.1:3100/ws',
  'VISION_ROBOT_EXECUTION_ENABLED=0',
]) {
  assert.equal(envExample.includes(setting), true, `missing .env example: ${setting}`);
}
assert.equal(launcher.includes('VISION_ROBOT_EXECUTION_ENABLED'), true);
assert.equal(launcher.includes('XVISION_PROXY_ENABLED'), true);

const originalExecution = process.env.VISION_ROBOT_EXECUTION_ENABLED;
delete process.env.VISION_ROBOT_EXECUTION_ENABLED;
delete require.cache[require.resolve('../config')];
assert.equal(require('../config').visionSafety.robotExecutionEnabled, false);
if (originalExecution === undefined) delete process.env.VISION_ROBOT_EXECUTION_ENABLED;
else process.env.VISION_ROBOT_EXECUTION_ENABLED = originalExecution;

console.log('PASS dual-service startup is documented and grasp execution defaults locked');
