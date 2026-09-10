'use strict';

const crypto = require('node:crypto');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonicalize(value[key])])
    );
  }
  return value;
}

function contentId(payload) {
  const bytes = JSON.stringify(canonicalize(payload));
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function vector3(value, { nonNegative = false } = {}) {
  return Array.isArray(value) && value.length === 3 && value.every(item =>
    Number.isFinite(item) && (!nonNegative || item >= 0)
  );
}

function offsetMatches(detected, commanded, offset) {
  return vector3(detected) && vector3(commanded) && vector3(offset) &&
    detected.every((value, index) =>
      Math.abs(value + offset[index] - commanded[index]) <= 1e-9
    );
}

function hashList(value, minimum = 1) {
  return Array.isArray(value) && value.length >= minimum &&
    value.every(item => typeof item === 'string' && SHA256_ID.test(item));
}

function pinnedModels(value) {
  return value && typeof value === 'object' && !Array.isArray(value) &&
    SHA256_ID.test(value.vision_config_id || '') &&
    typeof value.camera_registration_id === 'string' &&
    value.camera_registration_id.length > 0 &&
    typeof value.camera_mount_id === 'string' && value.camera_mount_id.length > 0 &&
    typeof value.grounding_model === 'string' && value.grounding_model.length > 0 &&
    /^[0-9a-f]{40}$/.test(value.grounding_revision || '') &&
    SHA256_ID.test(value.grounding_weights_sha256 || '') &&
    typeof value.sam_model === 'string' && value.sam_model.length > 0 &&
    /^[0-9a-f]{40}$/.test(value.sam_revision || '') &&
    SHA256_ID.test(value.sam_weights_sha256 || '');
}

function buildActionEvidence(input = {}) {
  if (!Number.isSafeInteger(input.stableId) || input.stableId < 1 || input.stableId > 5 ||
      typeof input.requestId !== 'string' || !input.requestId ||
      !Number.isSafeInteger(input.motionEpoch) || input.motionEpoch < 0 ||
      !hashList(input.sourceVisionEvidenceIds, 3) ||
      !hashList(input.sourcePreviewIds, 3) || !hashList(input.sourceArmStateIds, 3) ||
      input.sourcePreviewIds.length !== input.sourceVisionEvidenceIds.length ||
      input.sourceArmStateIds.length !== input.sourceVisionEvidenceIds.length ||
      !Array.isArray(input.sourceObservedAtMs) ||
      input.sourceObservedAtMs.length !== input.sourceVisionEvidenceIds.length ||
      !input.sourceObservedAtMs.every(Number.isFinite) ||
      !SHA256_ID.test(input.calibrationId || '') ||
      !SHA256_ID.test(input.actionConfigId || '') ||
      !SHA256_ID.test(input.pathValidationId || '') ||
      !pinnedModels(input.modelProvenance) ||
      input.modelProvenance.vision_config_id !== input.visionConfigId ||
      !SHA256_ID.test(input.visionConfigId || '') ||
      !offsetMatches(
        input.detectedGraspPointM,
        input.commandedFlangeGraspM,
        input.flangeOffsetBaseM,
      ) || !vector3(input.posePositionStdM, { nonNegative: true }) ||
      !vector3(input.eulerRad) || !Number.isFinite(input.baseSpreadM) ||
      input.baseSpreadM < 0 || input.baseSpreadM > 0.010 ||
      !Number.isFinite(input.widthM) || input.widthM <= 0 || input.widthM > 0.072) {
    throw new TypeError('action evidence input is invalid');
  }
  const payload = canonicalize({
    schema: 'thirdhand-action-evidence-v2',
    request_id: input.requestId,
    stable_id: input.stableId,
    motion_epoch: input.motionEpoch,
    source_vision_evidence_ids: [...input.sourceVisionEvidenceIds],
    source_preview_ids: [...input.sourcePreviewIds],
    source_arm_state_ids: [...input.sourceArmStateIds],
    source_observed_at_ms: [...input.sourceObservedAtMs],
    calibration_id: input.calibrationId,
    vision_config_id: input.visionConfigId,
    action_config_id: input.actionConfigId,
    path_validation_id: input.pathValidationId,
    model_provenance: { ...input.modelProvenance },
    detected_grasp_point_m: [...input.detectedGraspPointM],
    commanded_flange_grasp_point_m: [...input.commandedFlangeGraspM],
    flange_offset_base_m: [...input.flangeOffsetBaseM],
    base_spread_m: input.baseSpreadM,
    pose_position_std_m: [...input.posePositionStdM],
    width_m: input.widthM,
    euler_rad: [...input.eulerRad],
  });
  return Object.freeze({
    id: contentId(payload),
    payload: Object.freeze(payload),
  });
}

function validateActionEvidence(evidence, expectedId) {
  if (!evidence || typeof evidence !== 'object' ||
      evidence.payload?.schema !== 'thirdhand-action-evidence-v2' ||
      !SHA256_ID.test(expectedId || '') || evidence.id !== expectedId ||
      contentId(evidence.payload) !== expectedId) return false;
  const payload = evidence.payload;
  try {
    const rebuilt = buildActionEvidence({
      stableId: payload.stable_id,
      requestId: payload.request_id,
      motionEpoch: payload.motion_epoch,
      sourceVisionEvidenceIds: payload.source_vision_evidence_ids,
      sourcePreviewIds: payload.source_preview_ids,
      sourceArmStateIds: payload.source_arm_state_ids,
      sourceObservedAtMs: payload.source_observed_at_ms,
      calibrationId: payload.calibration_id,
      visionConfigId: payload.vision_config_id,
      actionConfigId: payload.action_config_id,
      pathValidationId: payload.path_validation_id,
      modelProvenance: payload.model_provenance,
      detectedGraspPointM: payload.detected_grasp_point_m,
      commandedFlangeGraspM: payload.commanded_flange_grasp_point_m,
      flangeOffsetBaseM: payload.flange_offset_base_m,
      baseSpreadM: payload.base_spread_m,
      posePositionStdM: payload.pose_position_std_m,
      widthM: payload.width_m,
      eulerRad: payload.euler_rad,
    });
    return rebuilt.id === expectedId;
  } catch {
    return false;
  }
}

module.exports = { buildActionEvidence, canonicalize, contentId, validateActionEvidence };
