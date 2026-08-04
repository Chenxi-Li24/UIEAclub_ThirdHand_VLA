'use strict';

const assert = require('assert/strict');
const { authorizeGrasp, trustedTargetFromDetection } = require('../grasp-authorization');

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
