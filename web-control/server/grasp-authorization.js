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

module.exports = {
  authorizeGrasp,
  trustedTargetFromDetection,
  MAX_TARGET_AGE_MS,
};
