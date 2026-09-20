'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

const { buildExecutionPlan, deriveExecutionGeometry } = require(
  '../../../src/thirdhand_va/action/grasp/execution_plan'
);
const { buildActionEvidence } = require(
  '../../../src/thirdhand_va/action/evidence/action_evidence'
);

const config = {
  content_id: `sha256:${'c'.repeat(64)}`,
  robot: {
    home_tolerance_deg: 0.5,
    presets: { home: [0, 15, -30, 5, 0, 0] },
  },
  motion: {
    pregrasp_offset_m: 0.10,
    lift_height_m: 0.12,
    linear_speed_m_s: 0.03,
  },
  gripper: {
    execution_max_width_m: 0.072,
    contact_min_width_m: 0.008,
    contact_max_width_m: 0.070,
    release_min_width_m: 0.074,
    physical_max_width_m: 0.080,
  },
  grasp: {
    flange_offset_base_m: [0.0475, 0.01, 0],
    offset_validated: true,
  },
  place: {
    strategy: 'fixed_xy_keep_grasp_z',
    validated: true,
    fixed_xy_m: [0.26783482212847776, 0.010668622392713049],
    euler_rad: [0.001938936, -0.075722729, -1.123057982],
    grasp_z_range_m: [0.16, 0.28],
    vertical_clearance_m: 0.10,
    home_preset: 'home',
    path_validation_id: `sha256:${'b'.repeat(64)}`,
  },
};

function target(overrides = {}) {
  const detectedGraspPointM = overrides.detectedGraspPointM ?? [0.40, 0.05, 0.18];
  const commandedFlangeGraspM = overrides.commandedFlangeGraspM ??
    detectedGraspPointM.map((value, index) =>
      value + config.grasp.flange_offset_base_m[index]);
  const base = {
    actionable: true,
    stableId: 2,
    requestId: 'req-2',
    evidenceId: `sha256:${'a'.repeat(64)}`,
    motionEpoch: 3,
    trackState: 'confirmed',
    depthValid: true,
    blockers: [],
    detectedGraspPointM,
    commandedFlangeGraspM,
    flangeOffsetBaseM: [...config.grasp.flange_offset_base_m],
    approachBase: [1, 0, 0],
    widthM: 0.06,
    eulerRad: [0, 0, 0],
    ...overrides,
  };
  const actionEvidence = buildActionEvidence({
    ...base,
    widthM: Math.min(base.widthM, 0.072),
    sourceVisionEvidenceIds: [1, 2, 3].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourcePreviewIds: [4, 5, 6].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourceArmStateIds: [7, 8, 9].map(value =>
      `sha256:${String(value).padStart(64, '0')}`),
    sourceObservedAtMs: [1000, 1010, 1020],
    calibrationId: `sha256:${'a'.repeat(64)}`,
    visionConfigId: `sha256:${'b'.repeat(64)}`,
    actionConfigId: config.content_id,
    pathValidationId: config.place.path_validation_id,
    modelProvenance: {
      vision_config_id: `sha256:${'b'.repeat(64)}`,
      camera_registration_id: 'debug-registration',
      camera_mount_id: 'debug-wrist-mount',
      grounding_model: 'debug/grounding',
      grounding_revision: '1'.repeat(40),
      grounding_weights_sha256: `sha256:${'d'.repeat(64)}`,
      sam_model: 'debug/sam',
      sam_revision: '2'.repeat(40),
      sam_weights_sha256: `sha256:${'e'.repeat(64)}`,
    },
    baseSpreadM: 0.002,
    posePositionStdM: [0.001, 0.001, 0.002],
  });
  return { ...base, evidenceId: actionEvidence.id, actionEvidence };
}

test('execution plan is immutable and covers the full pick-place path', () => {
  const plan = buildExecutionPlan(target(), config);

  assert.deepEqual(plan.detectedGraspM, [0.40, 0.05, 0.18]);
  assert.deepEqual(plan.commandedFlangeGraspM, [0.4475, 0.06, 0.18]);
  assert.deepEqual(plan.pregraspM, [0.3475, 0.06, 0.18]);
  assert.deepEqual(plan.finalApproachM, [0.4475, 0.06, 0.18]);
  assert.deepEqual(plan.liftM, [0.4475, 0.06, 0.30]);
  assert.deepEqual(plan.prePlaceM, [0.267834822128, 0.010668622393, 0.28]);
  assert.deepEqual(plan.placeM, [0.267834822128, 0.010668622393, 0.18]);
  assert.deepEqual(plan.retreatM, [0.267834822128, 0.010668622393, 0.28]);
  assert.equal(plan.homePreset, 'home');
  assert.deepEqual(plan.homeJointsDeg, [0, 15, -30, 5, 0, 0]);
  assert.equal(plan.homeToleranceDeg, 0.5);
  assert.equal(plan.widthM, 0.06);
  assert.equal(plan.contactMinWidthM, 0.008);
  assert.equal(plan.contactMaxWidthM, 0.070);
  assert.equal(plan.schema, 'thirdhand-execution-plan-v2');
  assert.deepEqual(plan.graspEulerRad, [0, 0, 0]);
  assert.deepEqual(
    plan.placeEulerRad,
    [0.001938936, -0.075722729, -1.123057982],
  );
  assert.equal(plan.pathValidationId, `sha256:${'b'.repeat(64)}`);
  assert.equal(plan.releaseMinWidthM, 0.074);
  assert.equal(plan.timeSecByPhase.final_approach, 3.334);
  assert.equal(plan.timeSecByPhase.lift, 4);
  assert.equal(plan.timeSecByPhase.lower, 3.334);
  assert.equal(plan.timeSecByPhase.retreat, 3.334);
  assert.equal(Object.isFrozen(plan), true);
  assert.equal(Object.isFrozen(plan.pregraspM), true);
  assert.equal(Object.isFrozen(plan.homeJointsDeg), true);
  assert.equal(Object.isFrozen(plan.timeSecByPhase), true);
  assert.deepEqual(plan.transferSegments, [{
    position: [0.267834822128, 0.010668622393, 0.28],
    timeSec: plan.timeSecByPhase.transfer,
  }]);
  assert.equal(Object.isFrozen(plan.transferSegments), true);
  assert.equal(Object.isFrozen(plan.transferSegments[0]), true);
});

test('long low-speed transfer is split into protocol-safe linear segments', () => {
  const farConfig = {
    ...config,
    motion: { ...config.motion, lift_height_m: 0.25 },
    place: {
      ...config.place,
      fixed_xy_m: [0.282831634, -0.591124195],
      grasp_z_range_m: [0.04, 0.15],
      vertical_clearance_m: 0.25,
    },
  };

  const plan = buildExecutionPlan(target({
    detectedGraspPointM: [0.50, 0.35, 0.08],
  }), farConfig);

  assert.equal(plan.timeSecByPhase.transfer > 30, true);
  assert.equal(plan.transferSegments.length, 2);
  assert.equal(plan.transferSegments.every(segment => segment.timeSec <= 30), true);
  assert.deepEqual(plan.transferSegments.at(-1).position, plan.prePlaceM);
  assert.equal(
    Number(plan.transferSegments.reduce((sum, segment) => sum + segment.timeSec, 0).toFixed(3)),
    plan.timeSecByPhase.transfer,
  );
});

test('fixed XY placement keeps each validated commanded grasp Z', () => {
  const low = deriveExecutionGeometry({
    detectedGraspPointM: [0.40, 0.05, 0.18],
    commandedFlangeGraspM: [0.4475, 0.06, 0.18],
    approachBase: [1, 0, 0],
  }, config);
  const high = deriveExecutionGeometry({
    detectedGraspPointM: [0.40, 0.05, 0.26],
    commandedFlangeGraspM: [0.4475, 0.06, 0.26],
    approachBase: [1, 0, 0],
  }, config);

  assert.deepEqual(low.placeM, [0.267834822128, 0.010668622393, 0.18]);
  assert.deepEqual(low.prePlaceM, [0.267834822128, 0.010668622393, 0.28]);
  assert.equal(high.placeM[2], 0.26);
  assert.equal(high.prePlaceM[2], 0.36);
});

test('geometry rejects unvalidated offsets mismatch and out-of-range Z', () => {
  const fixture = {
    detectedGraspPointM: [0.40, 0.05, 0.18],
    commandedFlangeGraspM: [0.4475, 0.06, 0.18],
    approachBase: [1, 0, 0],
  };
  assert.throws(() => deriveExecutionGeometry(fixture, {
    ...config, grasp: { ...config.grasp, offset_validated: false },
  }), /grasp_offset_not_validated/);
  assert.throws(() => deriveExecutionGeometry({
    ...fixture, commandedFlangeGraspM: [0.40, 0.05, 0.18],
  }, config), /commanded_flange_grasp_mismatch/);
  assert.throws(() => deriveExecutionGeometry({
    ...fixture,
    detectedGraspPointM: [0.40, 0.05, 0.30],
    commandedFlangeGraspM: [0.4475, 0.06, 0.30],
  }, config), /grasp_z_out_of_validated_range/);
});

test('execution plan rejects motion speed above the 0.10 m/s safety ceiling', () => {
  assert.throws(
    () => buildExecutionPlan(target(), {
      ...config, motion: { ...config.motion, linear_speed_m_s: 0.101 },
    }),
    /motion config is invalid/
  );
});

test('execution plan rejects width above the 72 mm executable limit', () => {
  assert.throws(
    () => buildExecutionPlan(target({ widthM: 0.073 }), config),
    /grasp_width_exceeded/
  );
});

test('execution plan rejects non-actionable or unvalidated place input', () => {
  assert.throws(
    () => buildExecutionPlan(target({ actionable: false }), config),
    /target_not_actionable/
  );
  assert.throws(
    () => buildExecutionPlan(target(), {
      ...config, place: { ...config.place, validated: false },
    }),
    /place_not_validated/
  );
});

test('standalone geometry debugger exposes fixed XY dynamic Z without hardware', () => {
  const root = path.resolve(__dirname, '../../..');
  const completed = spawnSync(process.execPath, [
    'scripts/action/debug_execution_plan.js',
    '--fixture', 'tests/fixtures/integration/full-cycle.json',
  ], { cwd: root, encoding: 'utf8' });

  assert.equal(completed.status, 0, completed.stderr);
  const report = JSON.parse(completed.stdout);
  assert.deepEqual(report.waypoints.place_m, [0.267834822128, 0.010668622393, 0.18]);
  assert.deepEqual(report.flange_offset_base_m, [0.0475, 0.01, 0]);
  assert.equal(report.robot_control_enabled, false);
  assert.equal(report.hardware_connected, false);
  assert.deepEqual(report.blockers, []);
});
