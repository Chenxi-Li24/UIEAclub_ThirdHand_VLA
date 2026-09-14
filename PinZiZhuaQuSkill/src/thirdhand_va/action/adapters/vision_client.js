'use strict';

const { EventEmitter } = require('events');

const STATUSES = new Set(['searching', 'rejected', 'uncertain', 'unstable', 'ready']);
const TRACK_STATES = new Set(['tentative', 'confirmed', 'occluded', 'lost', 'retired']);
const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isFiniteVector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function isOptionalStableId(value) {
  return value === null || (Number.isSafeInteger(value) && value >= 1 && value <= 5);
}

function validPose(pose) {
  return isObject(pose) && pose.frame === 'xvisio_color' &&
    isFiniteVector(pose.point_m, 3) && isFiniteVector(pose.axis, 3) &&
    isFiniteVector(pose.approach, 3) && isFiniteVector(pose.position_std_m, 3) &&
    Number.isFinite(pose.width_m) && pose.width_m > 0 &&
    Number.isFinite(pose.depth_valid_ratio) && pose.depth_valid_ratio >= 0 &&
    pose.depth_valid_ratio <= 1;
}

function validTarget(target) {
  return isObject(target) && isOptionalStableId(target.stable_id) &&
    Number.isSafeInteger(target.backend_track_id) && target.backend_track_id >= 0 &&
    TRACK_STATES.has(target.track_state) &&
    Number.isSafeInteger(target.detection_id) && target.detection_id >= 0 &&
    typeof target.label === 'string' && target.label.length > 0 &&
    Number.isFinite(target.score) && target.score >= 0 && target.score <= 1 &&
    isFiniteVector(target.bbox_xyxy, 4) && isFiniteVector(target.centroid_xy, 2) &&
    typeof target.selected === 'boolean' && typeof target.depth_valid === 'boolean' &&
    Array.isArray(target.blockers) && target.blockers.every(
      blocker => typeof blocker === 'string' && blocker.length > 0
    );
}

function validModelProvenance(value) {
  return isObject(value) && SHA256_ID.test(value.vision_config_id || '') &&
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

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function normalizePose(pose) {
  if (pose === null) return null;
  return {
    frame: pose.frame,
    pointM: [...pose.point_m],
    axis: [...pose.axis],
    approach: [...pose.approach],
    widthM: pose.width_m,
    positionStdM: [...pose.position_std_m],
    depthValidRatio: pose.depth_valid_ratio,
  };
}

function normalizeTarget(target) {
  const normalized = {
    stableId: target.stable_id,
    backendTrackId: target.backend_track_id,
    trackState: target.track_state,
    detectionId: target.detection_id,
    label: target.label,
    score: target.score,
    bboxXyxy: [...target.bbox_xyxy],
    centroidXy: [...target.centroid_xy],
    selected: target.selected,
    depthValid: target.depth_valid,
    blockers: [...target.blockers],
  };
  for (const [source, destination] of [
    ['actionable', 'actionable'],
    ['calibration_validated', 'calibrationValidated'],
    ['arm_stationary', 'armStationary'],
    ['safety_approved', 'safetyApproved'],
  ]) {
    if (typeof target[source] === 'boolean') normalized[destination] = target[source];
  }
  if (isObject(target.grasp_preview)) normalized.graspPreview = { ...target.grasp_preview };
  return normalized;
}

class VisionClient extends EventEmitter {
  accept(message) {
    if (!isObject(message) || message.type !== 'detection_result' ||
        message.schema !== 'thirdhand-va-detection-v3' ||
        !Number.isSafeInteger(message.frame_id) || message.frame_id < 0 ||
        !Number.isSafeInteger(message.monotonic_ns) || message.monotonic_ns < 0 ||
        !isOptionalStableId(message.selected_stable_id) ||
        !(message.request_id === null ||
          (typeof message.request_id === 'string' && message.request_id.length > 0)) ||
        typeof message.camera_serial !== 'string' || message.camera_serial.length === 0 ||
        typeof message.registration_id !== 'string' || message.registration_id.length === 0 ||
        !validModelProvenance(message.model_provenance) ||
        !Number.isSafeInteger(message.motion_epoch) || message.motion_epoch < 0 ||
        typeof message.evidence_id !== 'string' || !SHA256_ID.test(message.evidence_id) ||
        !STATUSES.has(message.status) || message.robot_control_enabled !== false ||
        !Array.isArray(message.reasons) ||
        !message.reasons.every(reason => typeof reason === 'string' && reason.length > 0) ||
        !Number.isSafeInteger(message.stable_hits) || message.stable_hits < 0 ||
        !Number.isSafeInteger(message.window_size) || message.window_size < 1 ||
        message.stable_hits > message.window_size ||
        !Array.isArray(message.targets) || !message.targets.every(validTarget) ||
        !(message.pose === null || validPose(message.pose))) {
      return false;
    }

    const assignedIds = message.targets
      .map(target => target.stable_id)
      .filter(stableId => stableId !== null);
    if (new Set(assignedIds).size !== assignedIds.length) return false;

    const selectedTargets = message.targets.filter(target => target.selected);
    if (message.selected_stable_id === null) {
      if (selectedTargets.length !== 0) return false;
    } else if (selectedTargets.length !== 1 ||
               selectedTargets[0].stable_id !== message.selected_stable_id) {
      return false;
    }
    if (message.status === 'ready') {
      const target = selectedTargets[0];
      if (!validPose(message.pose) || !target || target.track_state !== 'confirmed' ||
          target.depth_valid !== true || target.blockers.length !== 0) return false;
    }

    const result = deepFreeze({
      schema: message.schema,
      frameId: message.frame_id,
      monotonicNs: message.monotonic_ns,
      observedAtMs: Number.isSafeInteger(message.ts) && message.ts >= 0
        ? message.ts : null,
      requestId: message.request_id,
      selectedStableId: message.selected_stable_id,
      cameraSerial: message.camera_serial,
      registrationId: message.registration_id,
      modelProvenance: { ...message.model_provenance },
      visionConfigId: message.model_provenance.vision_config_id,
      motionEpoch: message.motion_epoch,
      evidenceId: message.evidence_id,
      status: message.status,
      reasons: [...message.reasons],
      stableHits: message.stable_hits,
      windowSize: message.window_size,
      targets: message.targets.map(normalizeTarget),
      pose: normalizePose(message.pose),
      robotControlEnabled: false,
    });
    this.emit('result', result);
    return true;
  }
}

module.exports = { VisionClient };
