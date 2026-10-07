'use strict';

const { createHash } = require('node:crypto');
const { checkWorkspace } = require('../safety/workspace_check');
const { gripTargetToFlangePose } = require('./grip_transform');

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function rounded(values) {
  return values.map(value => Number(value.toFixed(12)));
}

function duration(from, to, speed) {
  return Math.max(0.001, Number((Math.hypot(...to.map(
    (value, index) => value - from[index]
  )) / speed).toFixed(3)));
}

function requireWorkspace(point, workspace, prefix) {
  const result = checkWorkspace(point, workspace, prefix);
  if (!result.allowed) throw new TypeError(result.blockers[0]);
}

function buildLiftOnlyPlan({ target, pose, config, requestId, motionEpoch }) {
  if (!vector3(target?.baseXyzM)) throw new TypeError('base_coordinates_unavailable');
  if (target.trackState !== 'confirmed' || target.depthValid !== true) {
    throw new TypeError('target_not_actionable');
  }
  if (!vector3(target.positionStdM) || target.positionStdM.some(value => value > 0.05)) {
    throw new TypeError('pose_spread_exceeded');
  }
  if (!Number.isFinite(pose?.widthM)) throw new TypeError('grasp_pose_unavailable');
  const widthM = pose.widthM;
  if (!Number.isFinite(widthM) || widthM <= 0 ||
      widthM > config.gripper.execution_max_width_m) {
    throw new TypeError('grasp_width_invalid');
  }
  const gripTransform = config.grasp?.grip_transform;
  if (gripTransform?.validated !== true ||
      !/^sha256:[0-9a-f]{64}$/.test(gripTransform?.validation_id ?? '')) {
    throw new TypeError('grip_transform_unverified');
  }
  const flangePose = gripTargetToFlangePose({
    positionM: target.baseXyzM,
    eulerRad: config.motion.grasp_euler_rad,
  }, gripTransform.matrix_4x4);
  const finalApproachM = rounded(flangePose.positionM);
  const pregraspM = rounded([
    finalApproachM[0], finalApproachM[1],
    finalApproachM[2] + config.motion.pregrasp_offset_m,
  ]);
  const liftM = rounded([
    finalApproachM[0], finalApproachM[1],
    finalApproachM[2] + config.motion.lift_height_m,
  ]);
  requireWorkspace(pregraspM, config.workspace_m, 'pregrasp_workspace');
  requireWorkspace(finalApproachM, config.workspace_m, 'commanded_grasp_workspace');
  requireWorkspace(liftM, config.workspace_m, 'lift_workspace');
  const speed = config.motion.linear_speed_m_s;
  if (!Number.isFinite(speed) || speed <= 0 || speed > 0.10) {
    throw new TypeError('motion_speed_invalid');
  }
  const evidenceId = `sha256:${createHash('sha256').update(JSON.stringify({
    stableId: target.stableId, requestId, motionEpoch, finalApproachM, liftM,
  })).digest('hex')}`;
  const idle = [...liftM];
  const mode = config.motion.fixed_table_grasp?.pregrasp_only === true
    ? 'pregrasp_only' : 'lift_only';
  return Object.freeze({
    schema: 'thirdhand-execution-plan-v2', mode,
    stableId: target.stableId, requestId, evidenceId, motionEpoch,
    pregraspSegments: [{ position: pregraspM,
      timeSec: duration(pregraspM, finalApproachM, speed) }],
    finalApproachM, liftM, prePlaceM: idle, placeM: idle, retreatM: idle,
    graspEulerRad: [...flangePose.eulerRad],
    placeEulerRad: [...flangePose.eulerRad],
    homePreset: 'unused', homeJointsDeg: [0, 0, 0, 0, 0, 0],
    homeToleranceDeg: 0.5, widthM,
    contactMinWidthM: config.gripper.contact_min_width_m,
    contactMaxWidthM: config.gripper.contact_max_width_m,
    releaseMinWidthM: config.gripper.release_min_width_m,
    releaseMaxWidthM: config.gripper.physical_max_width_m,
    timeSecByPhase: {
      final_approach: duration(pregraspM, finalApproachM, speed),
      lift: duration(finalApproachM, liftM, speed), transfer: 0.001,
      lower: 0.001, retreat: 0.001,
    },
    transferSegments: [{ position: idle, timeSec: 0.001 }],
    openPosition: 1, closePosition: 0, pathValidationId: null,
  });
}

module.exports = { buildLiftOnlyPlan };
