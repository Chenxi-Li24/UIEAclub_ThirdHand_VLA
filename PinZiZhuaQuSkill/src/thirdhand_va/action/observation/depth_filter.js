'use strict';

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function distance(left, right) {
  return Math.hypot(left[0] - right[0], left[1] - right[1], left[2] - right[2]);
}

function median(values) {
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

function medianPoint(points) {
  return [0, 1, 2].map(axis => median(points.map(point => point[axis])));
}

class DepthObservationFilter {
  constructor({
    stableWindow = 5,
    maxSpreadM = 0.010,
    maxAgeMs = 350,
    requiredStableSamples = 5,
  } = {}) {
    if (!Number.isInteger(stableWindow) || stableWindow < 3 || stableWindow > 15) {
      throw new TypeError('stableWindow must be an integer within [3, 15]');
    }
    for (const [name, value] of Object.entries({ maxSpreadM, maxAgeMs })) {
      if (!Number.isFinite(value) || value <= 0) throw new TypeError(`${name} must be positive`);
    }
    if (!Number.isSafeInteger(requiredStableSamples) || requiredStableSamples < 1) {
      throw new TypeError('requiredStableSamples must be a positive integer');
    }
    this.stableWindow = stableWindow;
    this.maxSpreadM = maxSpreadM;
    this.maxAgeMs = maxAgeMs;
    this.requiredStableSamples = requiredStableSamples;
    this.resetReference(0);
  }

  resetReference(motionEpoch = 0) {
    if (!Number.isSafeInteger(motionEpoch) || motionEpoch < 0) {
      throw new TypeError('motionEpoch must be a non-negative integer');
    }
    this.motionEpoch = motionEpoch;
    this.samples = [];
    this.sampleEvidence = [];
    this.lastPreviewId = null;
    this.referencePointM = null;
  }

  snapshot() {
    return {
      anchorPointM: this.referencePointM === null ? null : [...this.referencePointM],
      stableSamples: this.samples.length,
      sourceVisionEvidenceIds: this.sampleEvidence.map(item => item.visionEvidenceId),
      sourcePreviewIds: this.sampleEvidence.map(item => item.previewId),
      sourceArmStateIds: this.sampleEvidence.map(item => item.armStateId),
      sourceObservedAtMs: this.sampleEvidence.map(item => item.observedAtMs),
      motionEpoch: this.motionEpoch,
    };
  }

  observe(target, nowMs) {
    if (!Number.isFinite(nowMs)) {
      return { accepted: false, reason: 'target_observation_invalid', ...this.snapshot() };
    }
    if (target?.motionEpoch !== this.motionEpoch) {
      return { accepted: false, reason: 'motion_epoch_mismatch', ...this.snapshot() };
    }
    if (target?.armStationary !== true) {
      return { accepted: false, reason: 'arm_not_stationary', ...this.snapshot() };
    }
    const preview = target?.preview ?? target?.graspPreview;
    const pointM = preview?.pointM ?? preview?.grasp_xyz_m;
    const stableSamples = preview?.stableSamples ?? preview?.stable_samples;
    const previewId = preview?.previewId ?? preview?.preview_id;
    const usable = target?.depthValid === true && vector3(pointM) &&
      Number.isSafeInteger(stableSamples) &&
      stableSamples >= this.requiredStableSamples &&
      Number.isFinite(target.observedAtMs) && nowMs >= target.observedAtMs &&
      nowMs - target.observedAtMs <= this.maxAgeMs &&
      typeof previewId === 'string' && previewId.length > 0;
    const evidenceUsable = SHA256_ID.test(target?.evidenceId || '') &&
      SHA256_ID.test(previewId || '') && SHA256_ID.test(preview?.armStateId || '');
    if (!usable || !evidenceUsable) {
      return { accepted: false, reason: 'no_fresh_depth_target', ...this.snapshot() };
    }
    if (previewId === this.lastPreviewId) {
      return { accepted: false, reason: 'duplicate_vision_frame', ...this.snapshot() };
    }
    this.lastPreviewId = previewId;
    this.samples.push([...pointM]);
    this.sampleEvidence.push({
      visionEvidenceId: target.evidenceId,
      previewId,
      armStateId: preview.armStateId,
      observedAtMs: target.observedAtMs,
    });
    if (this.samples.length > this.stableWindow) {
      this.samples.shift();
      this.sampleEvidence.shift();
    }
    if (this.samples.length < this.stableWindow) {
      return { accepted: false, reason: 'base_stability_hits_insufficient',
        ...this.snapshot() };
    }

    const center = medianPoint(this.samples);
    const spreadM = Math.max(...this.samples.map(point => distance(point, center)));
    if (spreadM > this.maxSpreadM) {
      this.samples.shift();
      return { accepted: false, reason: 'base_pose_spread_too_large', spreadM,
        ...this.snapshot() };
    }
    this.referencePointM = center;
    return { accepted: true, reason: null, pointM: [...center], spreadM,
      ...this.snapshot() };
  }
}

module.exports = { DepthObservationFilter, medianPoint, distance };
