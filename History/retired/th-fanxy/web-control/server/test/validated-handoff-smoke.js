'use strict';

const assert = require('assert/strict');
const { GraspExecutionController } = require('../grasp-execution-controller');

const PREVIEW = `sha256:${'a'.repeat(64)}`;
const CALIBRATION = `sha256:${'b'.repeat(64)}`;
const EVIDENCE = [`sha256:${'c'.repeat(64)}`];

const alignedTarget = {
  identityId: 0,
  identityConfirmed: true,
  depthValid: true,
  armStationary: true,
  observedAtMs: 1_000,
  preview: {
    previewId: PREVIEW,
    identityId: 0,
    detectionId: 1,
    frame: 'robot_base',
    calibrationId: CALIBRATION,
    evidenceIds: EVIDENCE,
    pointM: [0.50, 0.17, 0.20],
    pregraspPointM: [0.40, 0.17, 0.20],
    retreatPointM: [0.35, 0.17, 0.20],
    yawRad: 0,
    widthM: 0.065,
    geometryAllowed: false,
    blockers: ['handeye_physical_validation_pending', 'handeye_activation_locked'],
    stableSamples: 5,
  },
};

const commands = [];
const controller = new GraspExecutionController({
  executionEnabled: true,
  physicalValidationExecutionEnabled: true,
  getRobotState: () => ({
    connected: true,
    moving: false,
    stateFresh: true,
    tcpPositionM: [0.36, 0.17, 0.20],
    tcpEulerRad: [0, 0, 0],
  }),
  getTarget: () => null,
  sendRobot: command => { commands.push(command); return true; },
  auditLog: { append: () => {} },
  nowMs: () => 1_100,
  idFactory: (() => {
    const ids = [
      '11111111-1111-4111-8111-111111111111',
      '22222222-2222-4222-8222-222222222222',
    ];
    return () => ids.shift();
  })(),
});

const result = controller.begin(
  { identityId: 0, previewId: PREVIEW },
  { pauseBeforeClose: true, validatedTarget: alignedTarget },
);

assert.equal(result.accepted, true);
assert.equal(result.phase, 'open');
assert.equal(commands[0].source, 'grasp:open');
console.log('PASS aligned visual target can be handed to grasp after close-range occlusion');
