'use strict';

// Pure geometry and evidence checks for the supervised CLI. Eligibility here
// is a preview result; it does not approve calibration or command hardware.
const finiteVector = (v, n = 3) => Array.isArray(v) && v.length === n && v.every(Number.isFinite);
const rounded = (v) => Number(v.toFixed(9));
const rejected = (reason) => ({ approved: false, reason });

function buildSupervisedPlan(observation, settings, now = Date.now()) {
  if (!settings || typeof settings !== 'object') return rejected('plan_settings_invalid');
  if (!observation || observation.valid !== true) return rejected(observation?.reason || 'target_lost');
  if (observation.target_id !== settings.targetId) return rejected('target_identity_changed');
  if (!Number.isFinite(now) || !Number.isFinite(observation.observed_at_ms) ||
      observation.observed_at_ms > now) return rejected('target_timestamp_invalid');
  if (!Number.isFinite(settings.maxObservationAgeMs) || settings.maxObservationAgeMs <= 0 || settings.maxObservationAgeMs > 300 ||
      now - observation.observed_at_ms > settings.maxObservationAgeMs) return rejected('target_stale');
  if (!Number.isFinite(observation.robot_state_ts) || observation.robot_state_ts > now ||
      !Number.isFinite(settings.maxRobotAgeMs) || settings.maxRobotAgeMs <= 0 || settings.maxRobotAgeMs > 500 ||
      now - observation.robot_state_ts > settings.maxRobotAgeMs) return rejected('robot_state_stale');
  if (observation.robot_state_ts < observation.observed_at_ms ||
      observation.robot_state_ts - observation.observed_at_ms > 500) {
    return rejected('pose_does_not_cover_frame_capture');
  }
  if (!Number.isSafeInteger(observation.frame_id) || observation.frame_id < 0) return rejected('frame_id_invalid');
  if (observation.supervised_base_candidate_valid !== true ||
      !Array.isArray(observation.robot_pose_blockers) || observation.robot_pose_blockers.length) {
    return rejected('base_candidate_invalid');
  }
  if (observation.handeye?.effective_matrix_semantics !== 'T_sdk_tool_camera') {
    return rejected('coordinate_frame_invalid');
  }
  if (!finiteVector(observation.base_xyz_m) || !finiteVector(observation.camera_xyz_m) ||
      !finiteVector(observation.pixel_uv, 2)) return rejected('target_pose_invalid');
  if (typeof observation.calibration_id !== 'string' ||
      !/^sha256:[0-9a-f]{64}$/.test(observation.calibration_id) ||
      observation.calibration_id !== observation.handeye?.calibration_id) return rejected('calibration_invalid');
  if (!finiteVector(settings.eulerRad) || !finiteVector(settings.graspOffsetM) ||
      !Number.isFinite(settings.pregraspHeightM) || settings.pregraspHeightM < 0.05 ||
      !Number.isFinite(settings.liftHeightM) || settings.liftHeightM < 0.05 ||
      settings.liftHeightM > 0.10) return rejected('plan_settings_invalid');
  if (settings.graspOffsetM.some((v) => v !== 0) ||
      !finiteVector(observation.candidate_offset_base_m_applied) ||
      observation.candidate_offset_base_m_applied.some((v) => v !== 0)) return rejected('unverified_base_offset');
  if (!Number.isFinite(observation.width_m) || observation.width_m <= 0 ||
      observation.width_m > 0.072) return rejected('grasp_width_invalid');
  const fixedHeight = settings.fixedGraspBaseZM !== undefined;
  if (fixedHeight && (!Number.isFinite(settings.fixedGraspBaseZM) ||
      settings.graspHeightBaseM !== undefined)) return rejected('plan_settings_invalid');

  const graspM = observation.base_xyz_m.map((v, i) => rounded(v + settings.graspOffsetM[i]));
  // For an upright bottle, a configured grasp plane is independent of which
  // part of its body the eye-in-hand camera currently sees. Preserve the
  // measured 3D point separately; never present the rule height as a depth sample.
  if (fixedHeight) graspM[2] = rounded(settings.fixedGraspBaseZM);
  const pregraspM = [...graspM];
  pregraspM[2] = rounded(graspM[2] + settings.pregraspHeightM);
  const retreatM = [...graspM];
  retreatM[2] = rounded(graspM[2] + settings.liftHeightM);
  if (![graspM, pregraspM, retreatM].every((p) => finiteVector(p))) return rejected('plan_geometry_invalid');
  const bounds = ['x', 'y', 'z'].map((axis) => settings.workspace?.[axis]);
  if (bounds.some((b) => !finiteVector(b, 2) || b[0] >= b[1]) ||
      [observation.base_xyz_m, graspM, pregraspM, retreatM].some((p) => p.some((v, i) => v < bounds[i][0] || v > bounds[i][1]))) {
    return rejected('workspace_rejected');
  }
  return {
    approved: true,
    executionApproved: false,
    physicalValidation: observation.physical_validation || 'pending',
    plan: {
      identityId: observation.target_id,
      calibrationId: observation.calibration_id,
      observedAtMs: observation.observed_at_ms,
      previewId: `${observation.target_id}:${observation.frame_id}:${observation.observed_at_ms}`,
      graspM, pregraspM, retreatM,
      graspHeightPolicy: fixedHeight ? 'fixed_base_z' : 'observed_target_z',
      fixedGraspBaseZM: fixedHeight ? settings.fixedGraspBaseZM : null,
      surfaceM: finiteVector(observation.base_surface_xyz_m) ? [...observation.base_surface_xyz_m] : null,
      estimatedCenterM: [...observation.base_xyz_m],
      widthM: observation.width_m,
      yawRad: settings.eulerRad[2],
      eulerRad: [...settings.eulerRad],
    },
  };
}

function motionDuration(from, to, maxSpeedMps) {
  if (!finiteVector(from) || !finiteVector(to) || !Number.isFinite(maxSpeedMps) ||
      maxSpeedMps <= 0 || maxSpeedMps > 0.03) throw new Error('invalid motion input');
  // README_API describes quintic waypoint timing. Use extra timing margin;
  // this requested duration is not a verified physical TCP peak-speed bound.
  const seconds = Math.max(2, 2.1875 * Math.hypot(...to.map((v, i) => v - from[i])) / maxSpeedMps);
  if (seconds > 30) throw new Error('motion duration exceeds bridge limit; split and review path');
  return Math.ceil(seconds * 1000) / 1000;
}

function verifyHold({ startZ, currentZ, elapsedMs, contact, visualConfirmed = false }) {
  const liftM = currentZ - startZ;
  const telemetryCriteriaPassed = [startZ, currentZ, elapsedMs].every(Number.isFinite) &&
    liftM >= 0.05 && elapsedMs >= 3000 && contact === true;
  return {
    passed: telemetryCriteriaPassed && visualConfirmed === true,
    telemetryCriteriaPassed,
    physicalEvidenceSource: visualConfirmed === true ? 'operator_visual_confirmation' : null,
    liftM,
    // TCP displacement/contact cannot prove the bottle itself left the table.
    requiresVisualConfirmation: true,
  };
}

module.exports = { buildSupervisedPlan, motionDuration, verifyHold };
