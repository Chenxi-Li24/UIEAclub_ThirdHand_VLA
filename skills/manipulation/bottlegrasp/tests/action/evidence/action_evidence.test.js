'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  buildActionEvidence, validateActionEvidence,
} = require('../../../src/thirdhand_va/action/evidence/action_evidence');

function input(overrides = {}) {
  return {
    stableId: 2,
    requestId: 'req-2',
    motionEpoch: 1,
    sourceVisionEvidenceIds: [1, 2, 3].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourcePreviewIds: [4, 5, 6].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourceArmStateIds: [7, 8, 9].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourceObservedAtMs: [1000, 1010, 1020],
    calibrationId: `sha256:${'a'.repeat(64)}`,
    visionConfigId: `sha256:${'b'.repeat(64)}`,
    actionConfigId: `sha256:${'c'.repeat(64)}`,
    pathValidationId: `sha256:${'d'.repeat(64)}`,
    modelProvenance: {
      vision_config_id: `sha256:${'b'.repeat(64)}`,
      camera_registration_id: 'debug-registration',
      camera_mount_id: 'debug-wrist-mount',
      grounding_model: 'debug/grounding',
      grounding_revision: '1'.repeat(40),
      grounding_weights_sha256: `sha256:${'e'.repeat(64)}`,
      sam_model: 'debug/sam',
      sam_revision: '2'.repeat(40),
      sam_weights_sha256: `sha256:${'f'.repeat(64)}`,
    },
    detectedGraspPointM: [0.4, 0.05, 0.18],
    commandedFlangeGraspM: [0.4475, 0.06, 0.18],
    flangeOffsetBaseM: [0.0475, 0.01, 0],
    baseSpreadM: 0.002,
    posePositionStdM: [0.001, 0.001, 0.002],
    widthM: 0.06,
    eulerRad: [0, 0, 0],
    ...overrides,
  };
}

test('action evidence binds executed base point to all source and artifact IDs', () => {
  const evidence = buildActionEvidence(input());

  assert.match(evidence.id, /^sha256:[0-9a-f]{64}$/);
  assert.equal(validateActionEvidence(evidence, evidence.id), true);
  assert.equal(evidence.payload.source_preview_ids.length, 3);
  assert.equal(evidence.payload.path_validation_id, `sha256:${'d'.repeat(64)}`);
  assert.equal(evidence.payload.schema, 'thirdhand-action-evidence-v2');
  assert.deepEqual(evidence.payload.detected_grasp_point_m, [0.4, 0.05, 0.18]);
  assert.deepEqual(evidence.payload.commanded_flange_grasp_point_m, [0.4475, 0.06, 0.18]);
  assert.deepEqual(evidence.payload.flange_offset_base_m, [0.0475, 0.01, 0]);
});

test('changing the executable base point invalidates the evidence ID', () => {
  const evidence = buildActionEvidence(input());
  const tampered = {
    ...evidence,
    payload: {
      ...evidence.payload,
      commanded_flange_grasp_point_m: [0.5, 0.05, 0.18],
    },
  };

  assert.equal(validateActionEvidence(tampered, evidence.id), false);
  assert.throws(() => buildActionEvidence(input({ sourcePreviewIds: [] })), /invalid/);
});

module.exports = { input };
