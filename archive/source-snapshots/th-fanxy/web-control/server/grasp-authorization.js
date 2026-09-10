'use strict';

const MAX_TARGET_AGE_MS = 250;
const CONTENT_ID_PATTERN = /^sha256:[0-9a-f]{64}$/;

function finiteVector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function contentId(value) {
  return typeof value === 'string' && CONTENT_ID_PATTERN.test(value) ? value : null;
}

function previewFromDetection(target) {
  const source = target?.grasp_preview ?? target?.preview;
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
  return {
    previewId: contentId(source.preview_id ?? source.previewId),
    identityId: Number(source.identity_id ?? source.identityId),
    detectionId: Number(source.detection_id ?? source.detectionId),
    frame: source.frame,
    calibrationId: contentId(source.calibration_id ?? source.calibrationId),
    evidenceIds: Array.isArray(source.evidence_ids ?? source.evidenceIds)
      ? [...(source.evidence_ids ?? source.evidenceIds)] : [],
    pointM: source.grasp_xyz_m ?? source.pointM,
    pregraspPointM: source.pregrasp_xyz_m ?? source.pregraspPointM,
    retreatPointM: source.retreat_xyz_m ?? source.retreatPointM,
    yawRad: Number(source.yaw_rad ?? source.yawRad),
    widthM: Number(source.width_m ?? source.widthM),
    stableSamples: Number(source.stable_samples ?? source.stableSamples),
    geometryAllowed: (source.allowed ?? source.geometryAllowed) === true,
    blockers: Array.isArray(source.blockers) ? [...source.blockers] : [],
  };
}

function trustedTargetFromDetection(target, eventObservedAtMs = Number.NaN) {
  const timestampCandidate = target?.observed_at_ms ?? eventObservedAtMs;
  const timestamp = typeof timestampCandidate === 'number' && Number.isFinite(timestampCandidate)
    ? timestampCandidate : Number.NaN;
  const identityId = Number(target?.identity_id ?? target?.id);
  return {
    id: identityId,
    identityId,
    actionable: target?.actionable === true,
    calibrationValidated: typeof target?.calibration_validated === 'boolean'
      ? target.calibration_validated : null,
    depthValid: target?.depth_valid === true || finiteVector(target?.pose?.xyz_m, 3),
    identityConfirmed: target?.identity_confirmed === true || target?.identity_status === 'confirmed',
    armStationary: typeof target?.arm_stationary === 'boolean' ? target.arm_stationary : null,
    safetyApproved: typeof target?.safety_approved === 'boolean' ? target.safety_approved : null,
    observedAtMs: timestamp,
    positionM: target?.position_m ?? target?.pose?.xyz_m,
    preview: previewFromDetection(target),
  };
}

function validPreview(preview, target) {
  if (!preview || preview.previewId === null || preview.calibrationId === null) return false;
  if (!Number.isSafeInteger(preview.identityId) || preview.identityId !== target.identityId ||
      !Number.isSafeInteger(preview.detectionId) || preview.detectionId < 0) return false;
  if (preview.frame !== 'robot_base' || !finiteVector(preview.pointM, 3) ||
      !finiteVector(preview.pregraspPointM, 3) || !finiteVector(preview.retreatPointM, 3)) return false;
  if (!Number.isFinite(preview.yawRad) || !Number.isFinite(preview.widthM) || preview.widthM <= 0) return false;
  if (!Number.isSafeInteger(preview.stableSamples) || preview.stableSamples < 5) return false;
  return preview.evidenceIds.length > 0 && preview.evidenceIds.every(value => contentId(value) !== null);
}

function authorizeGrasp({ executionEnabled, bridgeConnected, armMotionActive, target, nowMs }) {
  if (executionEnabled !== true) return { approved: false, reason: 'robot_execution_disabled' };
  if (bridgeConnected !== true) return { approved: false, reason: 'robot_not_connected' };
  if (armMotionActive === true) return { approved: false, reason: 'arm_motion_active' };
  if (!target || target.actionable !== true) return { approved: false, reason: 'target_not_actionable' };
  if (target.identityConfirmed !== true) {
    return { approved: false, reason: 'target_safety_evidence_incomplete' };
  }
  if (target.calibrationValidated === false || target.depthValid === false ||
      target.armStationary === false || target.safetyApproved === false) {
    return { approved: false, reason: 'target_safety_evidence_incomplete' };
  }
  if (!Number.isFinite(nowMs) || !Number.isFinite(target.observedAtMs)) {
    return { approved: false, reason: 'target_timestamp_invalid' };
  }
  if (nowMs < target.observedAtMs || nowMs - target.observedAtMs > MAX_TARGET_AGE_MS) {
    return { approved: false, reason: 'target_stale' };
  }
  if (!validPreview(target.preview, target)) {
    return { approved: false, reason: 'grasp_preview_invalid' };
  }
  if (target.preview.geometryAllowed !== true || target.preview.blockers.length !== 0) {
    return { approved: false, reason: 'grasp_geometry_blocked' };
  }
  const plan = {
    identityId: target.identityId,
    detectionId: target.preview.detectionId,
    previewId: target.preview.previewId,
    calibrationId: target.preview.calibrationId,
    evidenceIds: [...target.preview.evidenceIds],
    graspPointM: [...target.preview.pointM],
    pregraspPointM: [...target.preview.pregraspPointM],
    retreatPointM: [...target.preview.retreatPointM],
    yawRad: target.preview.yawRad,
    widthM: target.preview.widthM,
  };
  return { approved: true, plan };
}

module.exports = {
  authorizeGrasp,
  trustedTargetFromDetection,
  previewFromDetection,
  MAX_TARGET_AGE_MS,
};
