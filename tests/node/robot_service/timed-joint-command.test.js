'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { RobotController } = require('../../../services/robot/src/robot-controller');

for (const command of [
  { cmd: 'servo', joints: [20, 0, -10, 0, 0, 0] },
  { cmd: 'preset', name: 'zero' },
]) {
  test(`${command.cmd} forwards an explicit speed-limited duration`, () => {
    const controller = new RobotController({ speedScale: 0.05, minMoveTimeSec: 0.5, maxMoveTimeSec: 30 });
    controller.bridge.connected = true;
    controller.stateReady = true;
    controller.latestJointsDeg = [0, 0, -10, 0, 0, 0];
    controller.latestRobotStateAtMs = Date.now();
    const sent = [];
    controller.bridge.send = payload => { sent.push(payload); return true; };
    const replies = [];
    controller.handleCommand({ ...command, time_sec: 4, request_id: 'dummy-timed' }, reply => replies.push(reply));
    assert.deepEqual(replies, []);
    assert.equal(sent.length, 1);
    assert.equal(sent[0].time_sec, 4);
    assert.equal(sent[0].request_id, 'dummy-timed');
    assert.equal(sent[0].cmd, 'move_joint');
  });
}
