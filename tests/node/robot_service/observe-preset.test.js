'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { RobotController } = require('../../../services/robot/src/robot-controller');

const ROBOT_CONFIG = {
  speedScale: 0.05,
  minMoveTimeSec: 0.5,
  maxMoveTimeSec: 30,
};

test('observe is advertised to preset UIs with the operator-verified angles', () => {
  const controller = new RobotController(ROBOT_CONFIG);
  assert.deepEqual(
    controller.configMessage().presets.observe,
    [0, 90, -90, 90, 0, 0],
  );
});

test('observe preset sends the exact joint target through guarded motion', () => {
  const controller = new RobotController(ROBOT_CONFIG);
  controller.bridge.connected = true;
  controller.stateReady = true;
  controller.latestJointsDeg = [0, 0, -20, 0, 0, 0];
  controller.latestRobotStateAtMs = Date.now();

  const sent = [];
  controller.bridge.send = command => {
    sent.push(command);
    return true;
  };
  const replies = [];
  controller.handleCommand(
    { cmd: 'preset', name: 'observe', request_id: 'observe-test-1' },
    reply => replies.push(reply),
  );

  assert.deepEqual(replies, []);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].cmd, 'move_joint');
  assert.equal(sent[0].source, 'preset:observe');
  assert.equal(sent[0].request_id, 'observe-test-1');
  assert.deepEqual(sent[0].joints_rad, [0, Math.PI / 2, -Math.PI / 2, Math.PI / 2, 0, 0]);
  assert.ok(sent[0].time_sec >= ROBOT_CONFIG.minMoveTimeSec);
});
