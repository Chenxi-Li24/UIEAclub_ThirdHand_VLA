'use strict';

const assert = require('assert/strict');
const { VisualAlignController } = require('../visual-align-controller');

const PREVIEW = `sha256:${'a'.repeat(64)}`;
const target = {
  identityId: 0,
  identityConfirmed: false,
  depthValid: true,
  armStationary: true,
  observedAtMs: 1_000,
  preview: { previewId: PREVIEW },
};
let robot = {
  connected: true, moving: false, stateFresh: true, stationary: true,
  tcpPositionM: [0.30, 0.00, 0.18],
};
const commands = [];
let handoffContext = null;
const lock = {
  reset() {}, resetEvidence() {},
  snapshot() { return { locked: true, identityId: 0, anchorPointM: [0.50, 0.17, 0.20] }; },
  observe() {
    return { accepted: true, target, pointM: [0.50, 0.17, 0.20], measurementSource: 'depth' };
  },
};
const controller = new VisualAlignController({
  executionEnabled: true,
  allowCalibrationPending: true,
  getRobotState: () => robot,
  selectBottle: () => true,
  resetTargetPoseReference: () => true,
  sendRobot: command => { commands.push(command); return true; },
  startGrasp: (_command, context) => {
    handoffContext = context;
    return { accepted: true };
  },
  targetLock: lock,
  nowMs: () => 1_100,
  idFactory: (() => {
    const ids = [
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
      '33333333-3333-4333-8333-333333333333',
    ];
    return () => ids.shift();
  })(),
});

assert.equal(controller.start({ targetIndex: 1 }).accepted, true);
controller.onVisionTargets([target]);
robot = { ...robot, tcpPositionM: [0.35, 0.17, 0.30] };
controller.onRobotEvent({ type: 'command_complete', request_id: commands.at(-1).request_id, reached: true });
controller.onVisionTargets([target]);
robot = { ...robot, tcpPositionM: [0.35, 0.17, 0.20] };
controller.onRobotEvent({ type: 'command_complete', request_id: commands.at(-1).request_id, reached: true });
controller.onVisionTargets([target]);

assert.equal(controller.snapshot().phase, 'handed_off');
assert.equal(handoffContext.validatedTarget.identityId, 0);
assert.equal(handoffContext.validatedTarget.preview.previewId, PREVIEW);
assert.equal(handoffContext.validatedTarget.armStationary, true);
assert.equal(handoffContext.validatedTarget.identityConfirmed, true);
console.log('PASS visual alignment hands its locked target to grasp');
