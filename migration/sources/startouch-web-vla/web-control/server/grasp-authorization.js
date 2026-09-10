'use strict';

const MAX_TARGET_AGE_MS = 250;

function trustedTargetFromDetection(target) {
  const timestamp = target && typeof target.observed_at_ms === 'number' &&
    Number.isFinite(target.observed_at_ms)
    ? target.observed_at_ms
    : Number.NaN;
  return {
    id: Number(target?.id),
    actionable: target?.actionable === true,
    calibrationValidated: target?.calibration_validated === true,
    depthValid: target?.depth_valid === true,
    identityConfirmed: target?.identity_confirmed === true,
    armStationary: target?.arm_stationary === true,
    safetyApproved: target?.safety_approved === true,
    observedAtMs: timestamp,
    positionM: target?.position_m,
  };
}

function authorizeGrasp({
  executionEnabled,
  bridgeConnected,
  armMotionActive,
  target,
  nowMs,
}) {
  if (executionEnabled !== true) {
    return { approved: false, reason: 'robot_execution_disabled' };
  }
  if (bridgeConnected !== true) {
    return { approved: false, reason: 'robot_not_connected' };
  }
  if (armMotionActive === true) {
    return { approved: false, reason: 'arm_motion_active' };
  }
  if (!target || target.actionable !== true) {
    return { approved: false, reason: 'target_not_actionable' };
  }
  if (
    target.calibrationValidated !== true ||
    target.depthValid !== true ||
    target.identityConfirmed !== true ||
    target.armStationary !== true ||
    target.safetyApproved !== true
  ) {
    return { approved: false, reason: 'target_safety_evidence_incomplete' };
  }
  if (!Number.isFinite(nowMs) || !Number.isFinite(target.observedAtMs)) {
    return { approved: false, reason: 'target_timestamp_invalid' };
  }
  if (nowMs < target.observedAtMs || nowMs - target.observedAtMs > MAX_TARGET_AGE_MS) {
    return { approved: false, reason: 'target_stale' };
  }
  if (
    !Array.isArray(target.positionM) ||
    target.positionM.length !== 3 ||
    !target.positionM.every(Number.isFinite)
  ) {
    return { approved: false, reason: 'target_position_invalid' };
  }
  return { approved: true, positionM: [...target.positionM] };
}

function finiteVector(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function authorizeGraspPlan({
  executionEnabled,
  bridgeConnected,
  armMotionActive,
  robotStateFresh,
  target,
  nowMs,
  expectedIdentityId,
  expectedCalibrationId,
}) {
  const legacy = authorizeGrasp({
    executionEnabled,
    bridgeConnected,
    armMotionActive,
    target: target && { ...target, positionM: target.graspM },
    nowMs,
  });
  if (!legacy.approved) return legacy;
  if (robotStateFresh !== true) {
    return { approved: false, reason: 'robot_state_stale' };
  }
  if (target.previewAllowed !== true) {
    return { approved: false, reason: 'grasp_preview_not_allowed' };
  }
  if (!(
    (typeof target.identityId === 'string' && target.identityId.length > 0) ||
    (Number.isInteger(target.identityId) && target.identityId >= 0)
  )) {
    return { approved: false, reason: 'target_identity_invalid' };
  }
  if (typeof target.calibrationId !== 'string' || target.calibrationId.length === 0) {
    return { approved: false, reason: 'calibration_id_invalid' };
  }
  if (expectedIdentityId && target.identityId !== expectedIdentityId) {
    return { approved: false, reason: 'target_identity_changed' };
  }
  if (expectedCalibrationId && target.calibrationId !== expectedCalibrationId) {
    return { approved: false, reason: 'calibration_changed' };
  }
  if (!/^(?:sha256:)?[a-f0-9]{64}$/i.test(target.previewId || '')) {
    return { approved: false, reason: 'preview_id_invalid' };
  }
  if (!finiteVector(target.graspM) || !finiteVector(target.pregraspM) || !finiteVector(target.retreatM)) {
    return { approved: false, reason: 'grasp_geometry_invalid' };
  }
  if (!Number.isFinite(target.widthM) || target.widthM < 0.012 || target.widthM > 0.08) {
    return { approved: false, reason: 'grasp_width_invalid' };
  }
  if (!Number.isFinite(target.yawRad)) {
    return { approved: false, reason: 'grasp_yaw_invalid' };
  }

  return {
    approved: true,
    plan: Object.freeze({
      identityId: target.identityId,
      calibrationId: target.calibrationId,
      observedAtMs: target.observedAtMs,
      previewId: target.previewId,
      graspM: Object.freeze([...target.graspM]),
      pregraspM: Object.freeze([...target.pregraspM]),
      retreatM: Object.freeze([...target.retreatM]),
      widthM: target.widthM,
      yawRad: target.yawRad,
    }),
  };
}

module.exports = {
  authorizeGrasp,
  authorizeGraspPlan,
  trustedTargetFromDetection,
  MAX_TARGET_AGE_MS,
};
