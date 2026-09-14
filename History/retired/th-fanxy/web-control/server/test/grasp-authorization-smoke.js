'use strict';

const assert = require('assert/strict');
const { authorizeGrasp, trustedTargetFromDetection } = require('../grasp-authorization');

const trustedTarget = {
  id: 7,
  identityId: 7,
  actionable: true,
  calibrationValidated: true,
  depthValid: true,
  identityConfirmed: true,
  armStationary: true,
  safetyApproved: true,
  observedAtMs: 1000,
  positionM: [0.2, -0.1, 0.3],
  preview: {
    previewId: `sha256:${'a'.repeat(64)}`,
    identityId: 7,
    detectionId: 9,
    frame: 'robot_base',
    calibrationId: `sha256:${'b'.repeat(64)}`,
    evidenceIds: [`sha256:${'c'.repeat(64)}`],
    pointM: [0.2, -0.1, 0.3],
    pregraspPointM: [0.2, -0.1, 0.4],
    retreatPointM: [0.2, -0.1, 0.45],
    yawRad: 0.1,
    widthM: 0.04,
    stableSamples: 5,
    geometryAllowed: true,
    blockers: [],
  },
};

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: false,
    bridgeConnected: true,
    armMotionActive: false,
    target: trustedTarget,
    nowMs: 1100
  }),
  { approved: false, reason: 'robot_execution_disabled' }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: { ...trustedTarget, actionable: false },
    nowMs: 1100
  }),
  { approved: false, reason: 'target_not_actionable' }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: trustedTarget,
    nowMs: 1400
  }),
  { approved: false, reason: 'target_stale' }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: true,
    target: trustedTarget,
    nowMs: 1100
  }),
  { approved: false, reason: 'arm_motion_active' }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: { ...trustedTarget, safetyApproved: false },
    nowMs: 1100
  }),
  { approved: false, reason: 'target_safety_evidence_incomplete' }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: trustedTarget,
    nowMs: 1100
  }),
  {
    approved: true,
    plan: {
      identityId: 7,
      detectionId: 9,
      previewId: `sha256:${'a'.repeat(64)}`,
      calibrationId: `sha256:${'b'.repeat(64)}`,
      evidenceIds: [`sha256:${'c'.repeat(64)}`],
      graspPointM: [0.2, -0.1, 0.3],
      pregraspPointM: [0.2, -0.1, 0.4],
      retreatPointM: [0.2, -0.1, 0.45],
      yawRad: 0.1,
      widthM: 0.04,
    },
  }
);

assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: { ...trustedTarget, preview: { ...trustedTarget.preview, geometryAllowed: false,
      blockers: ['unstable_grasp_geometry'] } },
    nowMs: 1100,
  }),
  { approved: false, reason: 'grasp_geometry_blocked' },
);

console.log('PASS grasp authorization is fail-closed and ignores browser coordinates');

const missingTimestamp = trustedTargetFromDetection({ id: 7, position_m: [0.1, 0.2, 0.3] });
assert.equal(Number.isNaN(missingTimestamp.observedAtMs), true);
assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: { ...trustedTarget, observedAtMs: Number.NaN },
    nowMs: 1100
  }),
  { approved: false, reason: 'target_timestamp_invalid' }
);

const zeroTimestamp = trustedTargetFromDetection({
  id: 7,
  observed_at_ms: 0,
  position_m: [0.1, 0.2, 0.3]
});
assert.equal(zeroTimestamp.observedAtMs, 0);
assert.deepEqual(
  authorizeGrasp({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    target: { ...trustedTarget, observedAtMs: 0 },
    nowMs: 1100
  }),
  { approved: false, reason: 'target_stale' }
);

console.log('PASS detection timestamps never fall back to event delivery time');
