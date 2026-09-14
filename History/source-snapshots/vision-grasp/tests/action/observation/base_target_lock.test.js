'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { BaseFrameTargetLock } = require(
  '../../../src/thirdhand_va/action/observation/base_target_lock'
);

let frame = 0;
function target(pointM, overrides = {}) {
  frame += 1;
  const evidenceId = `sha256:${String(frame + 10).padStart(64, '0')}`;
  const visionConfigId = `sha256:${'b'.repeat(64)}`;
  const modelProvenance = {
    vision_config_id: visionConfigId,
    camera_registration_id: 'debug-registration',
    camera_mount_id: 'debug-wrist-mount',
    grounding_model: 'debug/grounding',
    grounding_revision: '1'.repeat(40),
    grounding_weights_sha256: `sha256:${'c'.repeat(64)}`,
    sam_model: 'debug/sam',
    sam_revision: '2'.repeat(40),
    sam_weights_sha256: `sha256:${'d'.repeat(64)}`,
  };
  return {
    stableId: 2,
    requestId: 'req-2',
    calibrationId: `sha256:${'c'.repeat(64)}`,
    motionEpoch: 0,
    trackState: 'confirmed',
    depthValid: true,
    actionable: true,
    calibrationValidated: true,
    safetyApproved: true,
    gripperReady: true,
    blockers: [],
    armStationary: true,
    observedAtMs: 1000,
    evidenceId,
    visionConfigId,
    modelProvenance,
    posePositionStdM: [0.001, 0.001, 0.002],
    preview: {
      pointM,
      stableSamples: 3,
      previewId: `sha256:${String(frame).padStart(64, '0')}`,
      armStateId: `sha256:${String(frame + 20).padStart(64, '0')}`,
      visionEvidenceId: evidenceId,
      visionConfigId,
      modelProvenance,
      allowed: true,
    },
    ...overrides,
  };
}

function stable(lock, pointM, overrides = {}) {
  let result;
  for (let index = 0; index < 3; index += 1) {
    result = lock.observe([target(pointM, overrides)], 1100);
  }
  return result;
}

test('request-bound stable ID lock requires new depth after every motion epoch', () => {
  const lock = new BaseFrameTargetLock({ stableWindow: 3, requiredStableSamples: 3 });
  lock.begin({ stableId: 2, requestId: 'req-2', motionEpoch: 0 });
  assert.deepEqual(stable(lock, [0.50, 0.10, 0.18]).pointM, [0.50, 0.10, 0.18]);

  lock.resetEvidence(1);
  const missing = lock.observe([target(null, {
    motionEpoch: 1, depthValid: false, preview: null,
  })], 1100);
  assert.equal(missing.accepted, false);
  assert.equal(missing.reason, 'target_preview_not_approved');

  const reacquired = stable(lock, [0.56, 0.13, 0.18], { motionEpoch: 1 });
  assert.equal(reacquired.accepted, true);
  assert.deepEqual(reacquired.pointM, [0.56, 0.13, 0.18]);
});

test('stable ID request and calibration conflicts are fail-closed', () => {
  const lock = new BaseFrameTargetLock({ stableWindow: 3 });
  lock.begin({ stableId: 2, requestId: 'req-2', motionEpoch: 0 });

  assert.equal(lock.observe([target([0.5, 0, 0.2], { stableId: 3 })], 1100).reason,
    'target_identity_conflict');
  assert.equal(lock.observe([target([0.5, 0, 0.2], { requestId: 'req-x' })], 1100).reason,
    'target_request_conflict');
  lock.observe([target([0.5, 0, 0.2])], 1100);
  assert.equal(lock.observe([target([0.5, 0, 0.2], {
    calibrationId: `sha256:${'d'.repeat(64)}`,
  })], 1100).reason, 'target_calibration_conflict');
});

test('motion lock refuses unapproved or blocked target evidence', () => {
  const lock = new BaseFrameTargetLock({ stableWindow: 3 });
  lock.begin({ stableId: 2, requestId: 'req-2', motionEpoch: 0 });

  assert.equal(lock.observe([target([0.5, 0, 0.2], {
    actionable: false,
  })], 1100).reason, 'target_not_actionable');
  assert.equal(lock.observe([target([0.5, 0, 0.2], {
    calibrationValidated: false,
  })], 1100).reason, 'target_calibration_not_validated');
  assert.equal(lock.observe([target([0.5, 0, 0.2], {
    safetyApproved: false,
  })], 1100).reason, 'target_safety_not_approved');
  assert.equal(lock.observe([target([0.5, 0, 0.2], {
    blockers: ['handeye_activation_locked'],
  })], 1100).reason, 'target_blocked');
  assert.equal(lock.snapshot().stableSamples, 0);
});
