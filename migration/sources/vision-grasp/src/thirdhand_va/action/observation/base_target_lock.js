'use strict';

const {
  DepthObservationFilter,
  medianPoint,
  distance,
} = require('./depth_filter');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function stableId(value) {
  return Number.isSafeInteger(value) && value >= 1 && value <= 5;
}

function previewOf(target) {
  return target?.preview ?? target?.graspPreview ?? null;
}

function calibrationIdOf(target) {
  const preview = previewOf(target);
  return target?.calibrationId ?? preview?.calibrationId ?? preview?.calibration_id ?? null;
}

function pinnedModelEvidence(target) {
  const model = target?.modelProvenance;
  return model && typeof model === 'object' &&
    SHA256_ID.test(target?.visionConfigId || '') &&
    model.vision_config_id === target.visionConfigId &&
    typeof model.camera_registration_id === 'string' &&
    model.camera_registration_id.length > 0 &&
    typeof model.camera_mount_id === 'string' && model.camera_mount_id.length > 0 &&
    typeof model.grounding_model === 'string' && model.grounding_model.length > 0 &&
    /^[0-9a-f]{40}$/.test(model.grounding_revision || '') &&
    SHA256_ID.test(model.grounding_weights_sha256 || '') &&
    typeof model.sam_model === 'string' && model.sam_model.length > 0 &&
    /^[0-9a-f]{40}$/.test(model.sam_revision || '') &&
    SHA256_ID.test(model.sam_weights_sha256 || '');
}

function sameModelEvidence(left, right) {
  const fields = [
    'vision_config_id', 'camera_registration_id', 'camera_mount_id',
    'grounding_model', 'grounding_revision', 'grounding_weights_sha256',
    'sam_model', 'sam_revision', 'sam_weights_sha256',
  ];
  return left && right && fields.every(field => left[field] === right[field]);
}

class BaseFrameTargetLock {
  constructor(options = {}) {
    this.depth = new DepthObservationFilter(options);
    this.maxPositionStdM = options.maxPositionStdM ?? 0.010;
    if (!Number.isFinite(this.maxPositionStdM) || this.maxPositionStdM <= 0 ||
        this.maxPositionStdM > 0.020) {
      throw new TypeError('maxPositionStdM must be within (0, 0.020]');
    }
    this.reset();
  }

  reset() {
    this.stableId = null;
    this.requestId = null;
    this.calibrationId = null;
    this.motionEpoch = 0;
    this.anchorPointM = null;
    this.depth.resetReference(0);
  }

  begin({ stableId: requestedId, requestId, calibrationId = null, motionEpoch = 0 }) {
    if (!stableId(requestedId) || typeof requestId !== 'string' || !requestId ||
        !(calibrationId === null || (typeof calibrationId === 'string' && calibrationId)) ||
        !Number.isSafeInteger(motionEpoch) || motionEpoch < 0) {
      throw new TypeError('target lock request is invalid');
    }
    this.stableId = requestedId;
    this.requestId = requestId;
    this.calibrationId = calibrationId;
    this.motionEpoch = motionEpoch;
    this.anchorPointM = null;
    this.depth.resetReference(motionEpoch);
  }

  resetEvidence(motionEpoch) {
    if (!Number.isSafeInteger(motionEpoch) || motionEpoch <= this.motionEpoch) {
      throw new TypeError('motion epoch must strictly increase');
    }
    this.motionEpoch = motionEpoch;
    this.anchorPointM = null;
    this.depth.resetReference(motionEpoch);
  }

  snapshot() {
    return {
      locked: this.stableId !== null,
      stableId: this.stableId,
      identityId: this.stableId,
      requestId: this.requestId,
      calibrationId: this.calibrationId,
      motionEpoch: this.motionEpoch,
      ...this.depth.snapshot(),
      anchorPointM: this.anchorPointM === null ? null : [...this.anchorPointM],
    };
  }

  observe(targets, nowMs) {
    if (this.stableId === null) {
      return { accepted: false, reason: 'target_lock_not_initialized', ...this.snapshot() };
    }
    if (!Array.isArray(targets)) {
      return { accepted: false, reason: 'target_observation_invalid', ...this.snapshot() };
    }
    const matches = targets.filter(target => target?.stableId === this.stableId);
    if (matches.length === 0) {
      const reason = targets.some(target => stableId(target?.stableId))
        ? 'target_identity_conflict' : 'selected_visual_target_missing';
      return { accepted: false, reason, ...this.snapshot() };
    }
    if (matches.length !== 1) {
      return { accepted: false, reason: 'target_selection_ambiguous', ...this.snapshot() };
    }
    const target = matches[0];
    if (target.requestId !== this.requestId) {
      return { accepted: false, reason: 'target_request_conflict', ...this.snapshot() };
    }
    if (target.trackState !== 'confirmed') {
      return { accepted: false, reason: 'target_not_confirmed', ...this.snapshot() };
    }
    if (target.actionable !== true) {
      return { accepted: false, reason: 'target_not_actionable', ...this.snapshot() };
    }
    if (target.calibrationValidated !== true) {
      return {
        accepted: false, reason: 'target_calibration_not_validated', ...this.snapshot(),
      };
    }
    if (target.safetyApproved !== true) {
      return { accepted: false, reason: 'target_safety_not_approved', ...this.snapshot() };
    }
    if (target.gripperReady !== true) {
      return { accepted: false, reason: 'target_gripper_not_ready', ...this.snapshot() };
    }
    const preview = previewOf(target);
    if (preview?.allowed !== true) {
      return { accepted: false, reason: 'target_preview_not_approved', ...this.snapshot() };
    }
    if (preview.visionEvidenceId !== target.evidenceId ||
        preview.visionConfigId !== target.visionConfigId ||
        !sameModelEvidence(preview.modelProvenance, target.modelProvenance)) {
      return { accepted: false, reason: 'target_preview_evidence_mismatch', ...this.snapshot() };
    }
    if (!pinnedModelEvidence(target)) {
      return { accepted: false, reason: 'target_model_evidence_invalid', ...this.snapshot() };
    }
    if (!Array.isArray(target.blockers) || target.blockers.length !== 0) {
      return { accepted: false, reason: 'target_blocked', ...this.snapshot() };
    }
    if (!SHA256_ID.test(target.evidenceId || '')) {
      return { accepted: false, reason: 'target_evidence_invalid', ...this.snapshot() };
    }
    if (!Array.isArray(target.posePositionStdM) ||
        target.posePositionStdM.length !== 3 ||
        !target.posePositionStdM.every(value => Number.isFinite(value) && value >= 0 &&
          value <= this.maxPositionStdM)) {
      return { accepted: false, reason: 'target_pose_spread_invalid', ...this.snapshot() };
    }
    const calibrationId = calibrationIdOf(target);
    if (!SHA256_ID.test(calibrationId || '')) {
      return { accepted: false, reason: 'target_calibration_missing', ...this.snapshot() };
    }
    if (this.calibrationId === null) this.calibrationId = calibrationId;
    if (calibrationId !== this.calibrationId) {
      return { accepted: false, reason: 'target_calibration_conflict', ...this.snapshot() };
    }

    if (this.anchorPointM !== null) {
      return {
        accepted: true,
        reason: null,
        target,
        pointM: [...this.anchorPointM],
        measurementSource: 'current_epoch_depth',
        ...this.snapshot(),
      };
    }
    const measured = this.depth.observe(target, nowMs);
    if (measured.accepted !== true) {
      return {
        accepted: false,
        reason: measured.reason === 'no_fresh_depth_target'
          ? 'fresh_depth_required' : measured.reason,
        target,
        ...this.snapshot(),
      };
    }
    this.anchorPointM = [...measured.pointM];
    return {
      accepted: true,
      reason: null,
      target,
      pointM: [...this.anchorPointM],
      spreadM: measured.spreadM,
      measurementSource: 'depth',
      ...this.snapshot(),
    };
  }
}

module.exports = { BaseFrameTargetLock, medianPoint, distance };
