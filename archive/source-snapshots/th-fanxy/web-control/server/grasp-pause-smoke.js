'use strict';

const assert = require('assert/strict');
const { GraspExecutionController } = require('./grasp-execution-controller');

const PREVIEW = `sha256:${'a'.repeat(64)}`;
const CALIBRATION = `sha256:${'b'.repeat(64)}`;
const IDS = [
  '11111111-1111-4111-8111-111111111111',
  '22222222-2222-4222-8222-222222222222',
  '33333333-3333-4333-8333-333333333333',
  '44444444-4444-4444-8444-444444444444',
  '55555555-5555-4555-8555-555555555555',
  '66666666-6666-4666-8666-666666666666',
];
let index = 0;
const commands = [];
const statuses = [];
const target = {
  identityId: 7, actionable: true, identityConfirmed: true, observedAtMs: 1000,
  preview: {
    previewId: PREVIEW, identityId: 7, detectionId: 12, frame: 'robot_base',
    calibrationId: CALIBRATION, evidenceIds: [CALIBRATION],
    pointM: [0.32, -0.11, 0.10], pregraspPointM: [0.24, -0.11, 0.10],
    retreatPointM: [0.32, -0.11, 0.20], yawRad: 0, widthM: 0.04,
    geometryAllowed: true, blockers: [], stableSamples: 5,
  },
};
const controller = new GraspExecutionController({
  executionEnabled: true,
  getRobotState: () => ({ connected: true, moving: false, stateFresh: true,
    tcpEulerRad: [0, 0, 0], tcpPositionM: [0.355, -0.11, 0.10] }),
  getTarget: () => target,
  sendRobot: command => { commands.push(command); return true; },
  auditLog: { append: () => {} },
  onStatus: status => statuses.push(status),
  nowMs: () => 1100,
  idFactory: () => IDS[index++],
  graspApproachAdvanceM: 0.035,
});

const started = controller.begin({ identityId: 7, previewId: PREVIEW },
  { pauseBeforeClose: true });
assert.equal(started.accepted, true);
controller.onRobotEvent({ type: 'command_complete', command: 'gripper',
  request_id: IDS[1], reached: true });
controller.onRobotEvent({ type: 'command_complete', command: 'move_l',
  request_id: IDS[2], reached: true });
const result = controller.onRobotEvent({ type: 'command_complete', command: 'move_l',
  request_id: IDS[3], reached: true });
assert.equal(result.status, 'paused_before_close');
assert.equal(controller.active, true);
assert.equal(commands.length, 3);
assert.deepEqual(commands.map(command => command.source),
  ['grasp:open', 'grasp:pregrasp', 'grasp:descend']);
assert.ok(Math.abs(commands[2].position[0] - 0.355) < 1e-9);
assert.equal(statuses.at(-1).phase, 'paused_before_close');
const adjusted = controller.adjustPausedPose([0, 0.005, 0]);
assert.equal(adjusted.accepted, true);
assert.equal(commands[3].source, 'grasp:validation_adjust');
assert.deepEqual(commands[3].position, [0.355, -0.105, 0.10]);
controller.onRobotEvent({ type: 'command_complete', command: 'move_l',
  request_id: IDS[4], reached: true });
const continued = controller.continueAfterPause();
assert.equal(continued.accepted, true);
assert.equal(commands.length, 5);
assert.equal(commands[4].source, 'grasp:close');
console.log('PASS validation reaches grasp pose and pauses before closing');
