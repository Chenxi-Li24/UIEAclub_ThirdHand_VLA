'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { buildLiftOnlyPlan } = require(
  '../../../src/thirdhand_va/action/grasp/lift_only_plan'
);

const config = {
  workspace_m: { x: [0.15, 0.66], y: [-0.65, 0.45], z: [0.04, 0.65] },
  motion: { pregrasp_offset_m: 0.10, lift_height_m: 0.15,
    linear_speed_m_s: 0.03, grasp_euler_rad: [0, 0, Math.PI / 2] },
  grasp: { grip_transform: { validated: true,
    validation_id: `sha256:${'d'.repeat(64)}`,
    matrix_4x4: [[1, 0, 0, 0.02], [0, 1, 0, 0],
      [0, 0, 1, 0], [0, 0, 0, 1]] } },
  gripper: { execution_max_width_m: 0.072, contact_min_width_m: 0.008,
    contact_max_width_m: 0.070, release_min_width_m: 0.074,
    physical_max_width_m: 0.080 },
};

test('builds a low-speed pregrasp, grasp and lift plan without place approval', () => {
  const plan = buildLiftOnlyPlan({
    target: { stableId: 2, trackState: 'confirmed', depthValid: true,
      blockers: ['bottle_height_unreliable'], baseXyzM: [0.30, 0.10, 0.20],
      positionStdM: [0.01, 0.01, 0.01] },
    pose: { widthM: 0.06 }, config,
    requestId: 'lift-2', motionEpoch: 4,
  });
  assert.equal(plan.mode, 'lift_only');
  assert.equal(plan.widthM, 0.06);
  assert.deepEqual(plan.finalApproachM, [0.3, 0.08, 0.2]);
  assert.deepEqual(plan.pregraspSegments[0].position, [0.3, 0.08, 0.3]);
  assert.deepEqual(plan.liftM, [0.3, 0.08, 0.35]);
  assert.equal(plan.pathValidationId, null);
});

test('rejects missing pose width and unvalidated grip transforms', () => {
  const target = { stableId: 2, trackState: 'confirmed', depthValid: true,
    blockers: [], baseXyzM: [0.30, 0.10, 0.20], positionStdM: [0, 0, 0] };
  assert.throws(() => buildLiftOnlyPlan({ target, pose: null, config,
    requestId: 'bad', motionEpoch: 0 }), /grasp_pose_unavailable/);
  assert.throws(() => buildLiftOnlyPlan({ target, pose: { widthM: 0.06 },
    config: { ...config, grasp: { grip_transform: { validated: false } } },
    requestId: 'bad', motionEpoch: 0 }), /grip_transform_unverified/);
});

test('rejects missing base coordinates and out-of-workspace lift', () => {
  assert.throws(() => buildLiftOnlyPlan({ target: { stableId: 2 }, pose: {}, config,
    requestId: 'bad', motionEpoch: 0 }), /base_coordinates_unavailable/);
  assert.throws(() => buildLiftOnlyPlan({
    target: { stableId: 2, trackState: 'confirmed', depthValid: true,
      blockers: [], baseXyzM: [0.30, 0.10, 0.60], positionStdM: [0, 0, 0] },
    pose: { widthM: 0.06 }, config, requestId: 'bad', motionEpoch: 0,
  }), /(?:pregrasp|lift)_workspace_z_out_of_bounds/);
});
