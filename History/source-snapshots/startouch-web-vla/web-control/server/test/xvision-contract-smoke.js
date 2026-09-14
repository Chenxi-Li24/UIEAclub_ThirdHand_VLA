'use strict';

const assert = require('assert/strict');
const { normalizeXVisionEvent } = require('../xvision-contract');

const HASH_A = `sha256:${'a'.repeat(64)}`;
const HASH_B = `sha256:${'b'.repeat(64)}`;

function fixture(overrides = {}) {
  return {
    type: 'detection_result',
    schema: 'thirdhand-va-detection-v2',
    ts: 5000,
    robot_control_enabled: true,
    hardware_validation: 'passed',
    status: 'ready',
    reasons: [],
    selection: { side: 'left', ordinal: 1 },
    pose: {
      frame: 'xvisio_color',
      point_m: [-0.03, 0.026, 0.194],
      depth_valid_ratio: 0.58,
      width_m: 0.062,
    },
    targets: [{
      detection_id: 4,
      identity_id: 9,
      identity_confirmed: true,
      label: 'bottle',
      score: 0.91,
      selected: true,
      left_ordinal: 1,
      right_ordinal: 3,
      observed_at_ms: 5000,
      actionable: true,
      calibration_validated: true,
      depth_valid: true,
      arm_stationary: true,
      safety_approved: true,
      grasp_preview: {
        allowed: true,
        blockers: [],
        preview_id: HASH_A,
        calibration_id: HASH_B,
        grasp_xyz_m: [0.555, 0.029, 0.294],
        pregrasp_xyz_m: [0.458, 0.013, 0.306],
        retreat_xyz_m: [0.458, 0.013, 0.356],
        width_m: 0.062,
        central_fraction: 0.58,
      },
    }],
    ...overrides,
  };
}

const normalized = normalizeXVisionEvent(fixture());
assert.equal(normalized.displayEvent.type, 'detection_result');
assert.equal(normalized.displayEvent.objects.length, 1);
assert.equal(normalized.displayEvent.objects[0].spatialLabel, 'L1/R3');
assert.equal(normalized.displayEvent.objects[0].selected, true);
assert.equal(normalized.displayEvent.objects[0].depthValidRatio, 0.58);
assert.equal(normalized.displayEvent.objects[0].graspWidthM, 0.062);
assert.deepEqual(normalized.trustedTarget.graspM, [0.555, 0.029, 0.294]);
assert.deepEqual(normalized.trustedTarget.pregraspM, [0.458, 0.013, 0.306]);
assert.deepEqual(normalized.trustedTarget.retreatM, [0.458, 0.013, 0.356]);
assert.equal(normalized.trustedTarget.previewId, HASH_A);
assert.equal(normalized.trustedTarget.calibrationId, HASH_B);
assert.equal(normalized.trustedTarget.actionable, true);
assert.notDeepEqual(normalized.trustedTarget.graspM, fixture().pose.point_m);

const injected = fixture({ position_m: [999, 999, 999] });
assert.deepEqual(normalizeXVisionEvent(injected).trustedTarget.graspM, [0.555, 0.029, 0.294]);

const mismatched = fixture({
  targets: [{
    ...fixture().targets[0],
    left_ordinal: 2,
    right_ordinal: 2,
  }],
});
assert.equal(normalizeXVisionEvent(mismatched).trustedTarget, null);
assert.equal(
  normalizeXVisionEvent(mismatched).displayEvent.objects[0].blockers.includes('selection_mismatch'),
  true
);

const duplicateSelected = fixture({
  targets: [fixture().targets[0], { ...fixture().targets[0], detection_id: 5 }],
});
assert.equal(normalizeXVisionEvent(duplicateSelected).trustedTarget, null);

const nonFinite = fixture({
  targets: [{
    ...fixture().targets[0],
    grasp_preview: {
      ...fixture().targets[0].grasp_preview,
      grasp_xyz_m: [Number.NaN, 0.029, 0.294],
    },
  }],
});
assert.equal(normalizeXVisionEvent(nonFinite).trustedTarget, null);

assert.equal(normalizeXVisionEvent(fixture({ ts: null })).trustedTarget, null);
assert.equal(normalizeXVisionEvent(fixture({ robot_control_enabled: false })).trustedTarget, null);
assert.equal(normalizeXVisionEvent(fixture({
  targets: [{
    ...fixture().targets[0],
    grasp_preview: { ...fixture().targets[0].grasp_preview, allowed: false },
  }],
})).trustedTarget, null);

assert.throws(
  () => normalizeXVisionEvent({ type: 'detection_result', schema: 'legacy' }),
  /unsupported XVisio detection schema/i
);

console.log('PASS XVisio contract separates display data from trusted grasp evidence');
