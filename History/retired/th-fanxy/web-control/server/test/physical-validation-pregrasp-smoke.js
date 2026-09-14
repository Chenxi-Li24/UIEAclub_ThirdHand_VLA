'use strict';
const assert = require('assert');
const { authorizePhysicalValidationPregrasp, authorizePhysicalValidationGrasp } =
  require('../physical-validation-pregrasp');
const id = `sha256:${'a'.repeat(64)}`;
const target = { identityId: 1, identityConfirmed: true, depthValid: true,
  armStationary: true, observedAtMs: 1000, preview: { previewId: id,
    calibrationId: id, identityId: 1, detectionId: 7, evidenceIds: [id],
    frame: 'robot_base', pointM: [0.407, 0.202, 0.084],
    pregraspPointM: [0.360, 0.160, 0.120],
    retreatPointM: [0.360, 0.160, 0.120], yawRad: 0, widthM: 0.04,
    stableSamples: 5, blockers: ['handeye_physical_validation_pending',
      'handeye_activation_locked'] } };
const robot = { connected: true, moving: false, stateFresh: true,
  tcpPositionM: [0.125, 0.010, 0.109], tcpEulerRad: [0.04, 0.70, 0.06] };
const approved = authorizePhysicalValidationPregrasp({ enabled: true,
  message: { identityId: 1, previewId: id }, target, robot, nowMs: 1100 });
assert.equal(approved.approved, true);
assert.deepEqual(approved.position, [0.407, 0.202, 0.184]);
const graspApproved = authorizePhysicalValidationGrasp({ enabled: true,
  target, robot, nowMs: 1100 });
assert.equal(graspApproved.approved, true);
assert.deepEqual(graspApproved.plan.graspPointM, [0.407, 0.202, 0.084]);
for (const [name, mutation, reason] of [
  ['disabled', { enabled: false }, 'physical_validation_disabled'],
  ['stale', { nowMs: 1300 }, 'validation_target_stale'],
  ['workspace', { target: { ...target, preview: { ...target.preview,
    pointM: [0.407, 0.202, 0.60] } } }, 'validation_workspace_rejected'],
  ['blocker', { target: { ...target, preview: { ...target.preview,
    blockers: [...target.preview.blockers, 'arm_state_stale'] } } },
    'unexpected_validation_blocker'],
]) {
  const result = authorizePhysicalValidationPregrasp({ enabled: true,
    message: { identityId: 1, previewId: id }, target, robot, nowMs: 1100,
    ...mutation });
  assert.equal(result.approved, false, name);
  assert.equal(result.reason, reason, name);
}
console.log('physical validation pregrasp smoke: PASS');
