'use strict';

const { checkWorkspace } = require('../safety/workspace_check');
const { evaluateHomeState } = require('../safety/home_gate');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;
const REQUIRED_BLOCKERS = Object.freeze([
  'handeye_activation_locked',
  'handeye_physical_validation_pending',
]);
const TRANSIENT_PREVIEW_BLOCKERS = Object.freeze([
  'arm_not_stationary',
  'frame_precedes_stationary_settle',
  'vision_not_ready',
]);

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function rounded(values) {
  return values.map(value => Number(value.toFixed(12)));
}

function distance(left, right) {
  return Math.hypot(...left.map((value, index) => value - right[index]));
}

function fail(reason) {
  return Object.freeze({ approved: false, reason });
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

/**
 * Build the one-time hand-eye commissioning path.
 *
 * This is deliberately separate from the production grasp state machine.  It
 * accepts only a numerically valid calibration whose *only* blockers are the
 * two physical-activation gates, and it never emits a gripper command.
 */
function authorizePregraspValidation({ targetId, target, robot, config, nowMs } = {}) {
  if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5 ||
      !robot || robot.connected !== true || robot.healthy !== true ||
      robot.moving === true || robot.stationary !== true || robot.stateFresh !== true ||
      robot.poseFrame !== 'robot_flange' || !vector3(robot.flangePositionM) ||
      !vector3(robot.flangeEulerRad) || !Number.isFinite(robot.gripperWidthM) ||
      robot.gripperWidthM < 0 || robot.gripperWidthM > 0.080) {
    return fail('robot_not_stationary');
  }
  if (!target || target.stable_id !== targetId || target.selected !== true ||
      target.track_state !== 'confirmed' || target.depth_valid !== true ||
      !Array.isArray(target.blockers) || target.blockers.length !== 0 ||
      !target.grasp_preview) return fail('validation_target_invalid');
  if (!Number.isFinite(nowMs) || !Number.isFinite(target.observed_at_ms) ||
      nowMs < target.observed_at_ms || nowMs - target.observed_at_ms > 500) {
    return fail('validation_target_stale');
  }

  const preview = target.grasp_preview;
  const blockers = Array.isArray(preview.blockers) ? [...preview.blockers].sort() : [];
  const requiredPresent = REQUIRED_BLOCKERS.every(item => blockers.includes(item));
  const extras = blockers.filter(item => !REQUIRED_BLOCKERS.includes(item));
  if (preview.allowed === false && requiredPresent && extras.length > 0 &&
      extras.every(item => TRANSIENT_PREVIEW_BLOCKERS.includes(item))) {
    return fail('validation_preview_pending');
  }
  if (preview.allowed !== false || blockers.length !== REQUIRED_BLOCKERS.length ||
      blockers.some((value, index) => value !== REQUIRED_BLOCKERS[index])) {
    return fail('unexpected_validation_blockers');
  }
  if (preview.frame !== 'robot_base' || !SHA256_ID.test(preview.calibration_id || '') ||
      !SHA256_ID.test(preview.preview_id || '') || !vector3(preview.grasp_xyz_m) ||
      !Number.isSafeInteger(preview.stable_samples) || preview.stable_samples < 4 ||
      !Number.isFinite(preview.width_m) || preview.width_m <= 0 ||
      preview.width_m > 0.072) return fail('validation_preview_invalid');

  const homePreset = config?.place?.home_preset;
  const home = evaluateHomeState({
    robotState: robot,
    homeJointsDeg: config?.robot?.presets?.[homePreset],
    toleranceDeg: config?.robot?.home_tolerance_deg,
  });
  if (home.allowed !== true) return fail(home.blockers[0] || 'robot_not_at_home');

  const workspace = config?.workspace_m;
  const motion = config?.motion;
  if (!workspace ||
      !Number.isFinite(motion?.pregrasp_offset_m) || motion.pregrasp_offset_m <= 0 ||
      !Number.isFinite(motion?.safe_transit_z_m) || motion.safe_transit_z_m <= 0 ||
      !Number.isFinite(motion?.linear_speed_m_s) || motion.linear_speed_m_s <= 0 ||
      motion.linear_speed_m_s > 0.10) return fail('validation_config_invalid');

  // Commissioning is deliberately clearance-only.  A grasp/flange offset is
  // part of the production tool geometry and must not be smuggled into the
  // hand-eye check before that geometry has its own physical approval.
  const observationM = rounded([
    preview.grasp_xyz_m[0], preview.grasp_xyz_m[1], motion.safe_transit_z_m,
  ]);
  if (motion.safe_transit_z_m <
      preview.grasp_xyz_m[2] + motion.pregrasp_offset_m + 0.05) {
    return fail('safe_transit_clearance_insufficient');
  }
  const positions = [
    rounded([
      robot.flangePositionM[0], robot.flangePositionM[1], motion.safe_transit_z_m,
    ]),
    observationM,
  ];
  if (positions.some(position =>
    checkWorkspace(position, workspace, 'commissioning').allowed !== true
  )) return fail('validation_workspace_rejected');

  // Keep the measured flange orientation fixed.  Rotating a long end
  // effector during horizontal travel creates an unvalidated swept volume.
  const eulers = [robot.flangeEulerRad, robot.flangeEulerRad];
  const phases = ['safe_height', 'over_target_clearance'];
  let previous = robot.flangePositionM;
  const stages = positions.map((position, index) => {
    const displacementM = distance(previous, position);
    previous = position;
    if (displacementM > 0.50) return null;
    return {
      phase: phases[index],
      position,
      euler: rounded(eulers[index]),
      timeSec: Math.min(30, Math.max(
        1, Number((displacementM / motion.linear_speed_m_s).toFixed(3))
      )),
    };
  });
  if (stages.includes(null)) return fail('validation_move_too_large');

  return deepFreeze({
    approved: true,
    targetId,
    calibrationId: preview.calibration_id,
    previewId: preview.preview_id,
    detectedGraspM: rounded(preview.grasp_xyz_m),
    observationM,
    widthM: preview.width_m,
    stages,
    commandsGripper: false,
    commandsDescent: false,
  });
}

module.exports = { authorizePregraspValidation, REQUIRED_BLOCKERS };
