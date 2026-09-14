'use strict';

const assert = require('assert/strict');
const {
  authorizeGrasp,
  authorizeGraspPlan,
  trustedTargetFromDetection,
} = require('../grasp-authorization');

const trustedTarget = {
  id: 7,
  actionable: true,
  calibrationValidated: true,
  depthValid: true,
  identityConfirmed: true,
  armStationary: true,
  safetyApproved: true,
  observedAtMs: 1000,
  positionM: [0.2, -0.1, 0.3]
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
  { approved: true, positionM: [0.2, -0.1, 0.3] }
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

const trustedPlanTarget = {
  ...trustedTarget,
  identityId: 'bottle-L1',
  calibrationId: 'cal-2026-08-17',
  previewId: 'a'.repeat(64),
  previewAllowed: true,
  graspM: [0.3, 0.02, 0.12],
  pregraspM: [0.3, 0.02, 0.20],
  retreatM: [0.3, 0.02, 0.24],
  widthM: 0.04,
  yawRad: 0,
};

assert.deepEqual(
  authorizeGraspPlan({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    robotStateFresh: true,
    target: trustedPlanTarget,
    nowMs: 1100,
  }),
  {
    approved: true,
    plan: {
      identityId: 'bottle-L1',
      calibrationId: 'cal-2026-08-17',
      observedAtMs: 1000,
      previewId: 'a'.repeat(64),
      graspM: [0.3, 0.02, 0.12],
      pregraspM: [0.3, 0.02, 0.20],
      retreatM: [0.3, 0.02, 0.24],
      widthM: 0.04,
      yawRad: 0,
    },
  }
);

assert.deepEqual(
  authorizeGraspPlan({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    robotStateFresh: true,
    target: { ...trustedPlanTarget, widthM: 0.2 },
    nowMs: 1100,
  }),
  { approved: false, reason: 'grasp_width_invalid' }
);

assert.deepEqual(
  authorizeGraspPlan({
    executionEnabled: true,
    bridgeConnected: true,
    armMotionActive: false,
    robotStateFresh: false,
    target: trustedPlanTarget,
    nowMs: 1100,
  }),
  { approved: false, reason: 'robot_state_stale' }
);

console.log('PASS grasp plans require fresh robot state and bounded server-side geometry');
