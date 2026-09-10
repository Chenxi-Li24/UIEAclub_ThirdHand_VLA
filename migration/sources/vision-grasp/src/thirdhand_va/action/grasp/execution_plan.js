'use strict';

const { validateActionEvidence } = require('../evidence/action_evidence');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function vector(value, name) {
  if (!Array.isArray(value) || value.length !== 3 || !value.every(Number.isFinite)) {
    throw new TypeError(`${name} must be a finite xyz vector`);
  }
  return [...value];
}

function roundedVector(values) {
  return values.map(value => Number(value.toFixed(12)));
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function distance(left, right) {
  return Math.hypot(...left.map((value, index) => right[index] - value));
}

function durationAtSpeed(from, to, speedMPerSec) {
  return Math.max(0.001, Math.ceil(distance(from, to) / speedMPerSec * 1000) / 1000);
}

function segmentLinearPath(from, to, speedMPerSec, maxDurationSec = 30) {
  const start = vector(from, 'linear path start');
  const finish = vector(to, 'linear path finish');
  if (!Number.isFinite(speedMPerSec) || speedMPerSec <= 0 ||
      !Number.isFinite(maxDurationSec) || maxDurationSec <= 0) {
    throw new TypeError('linear path limits are invalid');
  }
  const totalTimeSec = durationAtSpeed(start, finish, speedMPerSec);
  const count = Math.ceil(totalTimeSec / maxDurationSec);
  const totalMillis = Math.round(totalTimeSec * 1000);
  const baseMillis = Math.floor(totalMillis / count);
  const extraMillis = totalMillis % count;
  return deepFreeze(Array.from({ length: count }, (_, index) => {
    const fraction = (index + 1) / count;
    return {
      position: roundedVector(start.map(
        (value, axis) => value + (finish[axis] - value) * fraction
      )),
      timeSec: (baseMillis + (index < extraMillis ? 1 : 0)) / 1000,
    };
  }));
}

function deriveExecutionGeometry(target, config) {
  if (config?.grasp?.offset_validated !== true) {
    throw new TypeError('grasp_offset_not_validated');
  }
  if (config?.place?.validated !== true) throw new TypeError('place_not_validated');
  if (config.place.strategy !== 'fixed_xy_keep_grasp_z') {
    throw new TypeError('place_strategy_invalid');
  }
  const detectedGraspM = vector(target?.detectedGraspPointM, 'detectedGraspPointM');
  const commandedInput = vector(
    target?.commandedFlangeGraspM, 'commandedFlangeGraspM'
  );
  const flangeOffsetBaseM = vector(
    config.grasp.flange_offset_base_m, 'grasp.flange_offset_base_m'
  );
  const commandedFlangeGraspM = roundedVector(detectedGraspM.map(
    (value, index) => value + flangeOffsetBaseM[index]
  ));
  if (!sameVector(commandedFlangeGraspM, commandedInput)) {
    throw new TypeError('commanded_flange_grasp_mismatch');
  }
  const range = config.place.grasp_z_range_m;
  if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isFinite) ||
      range[0] > range[1] || commandedFlangeGraspM[2] < range[0] ||
      commandedFlangeGraspM[2] > range[1]) {
    throw new TypeError('grasp_z_out_of_validated_range');
  }
  const fixedXY = config.place.fixed_xy_m;
  if (!Array.isArray(fixedXY) || fixedXY.length !== 2 ||
      !fixedXY.every(Number.isFinite)) throw new TypeError('fixed_xy_invalid');
  const clearance = config.place.vertical_clearance_m;
  const pregraspOffset = config.motion?.pregrasp_offset_m;
  const liftHeight = config.motion?.lift_height_m;
  if (![clearance, pregraspOffset, liftHeight].every(
    value => Number.isFinite(value) && value > 0
  )) throw new TypeError('motion config is invalid');
  const approach = vector(target?.approachBase, 'approachBase');
  const norm = Math.hypot(...approach);
  if (norm < 1e-9) throw new TypeError('approachBase must be non-zero');
  const unitApproach = approach.map(value => value / norm);
  const placeM = roundedVector([
    fixedXY[0], fixedXY[1], commandedFlangeGraspM[2],
  ]);
  const safePlaceZ = Number((placeM[2] + clearance).toFixed(12));
  return deepFreeze({
    detectedGraspM: roundedVector(detectedGraspM),
    commandedFlangeGraspM,
    flangeOffsetBaseM: roundedVector(flangeOffsetBaseM),
    pregraspM: roundedVector(commandedFlangeGraspM.map(
      (value, index) => value - unitApproach[index] * pregraspOffset
    )),
    liftM: roundedVector([
      commandedFlangeGraspM[0], commandedFlangeGraspM[1],
      commandedFlangeGraspM[2] + liftHeight,
    ]),
    prePlaceM: roundedVector([placeM[0], placeM[1], safePlaceZ]),
    placeM,
    retreatM: roundedVector([placeM[0], placeM[1], safePlaceZ]),
  });
}

/**
 * Build only the immutable robot-agnostic path data.  The sequence mirrors the
 * proven TH-Fanxy controller (pregrasp, linear close, lift, place, retreat,
 * Home) without importing its browser, Express, or process-global state.
 */
function buildExecutionPlan(target, config) {
  if (!target || target.actionable !== true || target.trackState !== 'confirmed' ||
      target.depthValid !== true || !Array.isArray(target.blockers) ||
      target.blockers.length !== 0) throw new TypeError('target_not_actionable');
  if (!Number.isSafeInteger(target.stableId) || target.stableId < 1 || target.stableId > 5 ||
      typeof target.requestId !== 'string' || target.requestId.length === 0 ||
      typeof target.evidenceId !== 'string' || !SHA256_ID.test(target.evidenceId) ||
      !Number.isSafeInteger(target.motionEpoch) || target.motionEpoch < 0) {
    throw new TypeError('target evidence contract is invalid');
  }
  if (!config || !config.place || config.place.validated !== true) {
    throw new TypeError('place_not_validated');
  }
  if (!SHA256_ID.test(config.place.path_validation_id || '')) {
    throw new TypeError('post_release_path_not_validated');
  }
  const geometry = deriveExecutionGeometry(target, config);
  if (!Number.isFinite(target.widthM) || target.widthM <= 0) {
    throw new TypeError('grasp_width_invalid');
  }
  const maxWidth = config.gripper && config.gripper.execution_max_width_m;
  if (!Number.isFinite(maxWidth) || maxWidth <= 0 || maxWidth > 0.072 ||
      target.widthM > maxWidth) throw new TypeError('grasp_width_exceeded');
  if (!validateActionEvidence(target.actionEvidence, target.evidenceId)) {
    throw new TypeError('action_evidence_invalid');
  }
  const linearSpeed = config.motion && config.motion.linear_speed_m_s;
  if (!Number.isFinite(linearSpeed) || linearSpeed <= 0 || linearSpeed > 0.10) {
    throw new TypeError('motion config is invalid');
  }
  if (typeof config.place.home_preset !== 'string' || !config.place.home_preset) {
    throw new TypeError('home preset is invalid');
  }
  const homeJointsDeg = config.robot?.presets?.[config.place.home_preset];
  if (!Array.isArray(homeJointsDeg) || homeJointsDeg.length !== 6 ||
      !homeJointsDeg.every(Number.isFinite) ||
      !Number.isFinite(config.robot?.home_tolerance_deg) ||
      config.robot.home_tolerance_deg <= 0 || config.robot.home_tolerance_deg > 2.0) {
    throw new TypeError('home definition is invalid');
  }
  const finalApproachM = geometry.commandedFlangeGraspM;
  const { pregraspM, liftM, prePlaceM, placeM, retreatM } = geometry;
  const timeSecByPhase = {
    final_approach: durationAtSpeed(pregraspM, finalApproachM, linearSpeed),
    lift: durationAtSpeed(finalApproachM, liftM, linearSpeed),
    transfer: durationAtSpeed(liftM, prePlaceM, linearSpeed),
    lower: durationAtSpeed(prePlaceM, placeM, linearSpeed),
    retreat: durationAtSpeed(placeM, retreatM, linearSpeed),
  };
  const transferSegments = segmentLinearPath(liftM, prePlaceM, linearSpeed);
  const evidence = target.actionEvidence.payload;
  if (evidence.request_id !== target.requestId || evidence.stable_id !== target.stableId ||
      evidence.motion_epoch !== target.motionEpoch ||
      evidence.action_config_id !== config.content_id ||
      evidence.path_validation_id !== config.place.path_validation_id ||
      !sameVector(evidence.detected_grasp_point_m, geometry.detectedGraspM) ||
      !sameVector(
        evidence.commanded_flange_grasp_point_m,
        geometry.commandedFlangeGraspM,
      ) ||
      !sameVector(evidence.flange_offset_base_m, geometry.flangeOffsetBaseM) ||
      !sameVector(evidence.euler_rad, target.eulerRad ?? [0, 0, 0]) ||
      Math.abs(evidence.width_m - target.widthM) > 1e-9) {
    throw new TypeError('action_evidence_execution_mismatch');
  }
  return deepFreeze({
    schema: 'thirdhand-execution-plan-v2',
    stableId: target.stableId,
    requestId: target.requestId,
    evidenceId: target.evidenceId,
    motionEpoch: target.motionEpoch,
    detectedGraspM: geometry.detectedGraspM,
    commandedFlangeGraspM: geometry.commandedFlangeGraspM,
    flangeOffsetBaseM: geometry.flangeOffsetBaseM,
    pregraspM,
    finalApproachM,
    liftM,
    prePlaceM,
    placeM,
    retreatM,
    graspEulerRad: roundedVector(target.eulerRad ?? [0, 0, 0]),
    placeEulerRad: roundedVector(vector(config.place.euler_rad, 'place.euler_rad')),
    homePreset: config.place.home_preset,
    homeJointsDeg: [...homeJointsDeg],
    homeToleranceDeg: config.robot.home_tolerance_deg,
    widthM: target.widthM,
    contactMinWidthM: config.gripper.contact_min_width_m,
    contactMaxWidthM: config.gripper.contact_max_width_m,
    releaseMinWidthM: config.gripper.release_min_width_m,
    releaseMaxWidthM: config.gripper.physical_max_width_m,
    timeSecByPhase,
    transferSegments,
    openPosition: 1.0,
    closePosition: 0.0,
    pathValidationId: config.place.path_validation_id,
    calibrationId: evidence.calibration_id,
    visionConfigId: evidence.vision_config_id,
    actionConfigId: evidence.action_config_id,
    actionEvidence: target.actionEvidence,
  });
}

function sameVector(left, right) {
  return vector(left, 'evidence vector').every(
    (value, index) => Math.abs(value - right[index]) <= 1e-9
  );
}

module.exports = { buildExecutionPlan, deriveExecutionGeometry, segmentLinearPath };
