'use strict';

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
    this.resetReference();
  }

  resetReference() {
    this.samples = [];
    this.lastPreviewId = null;
    this.referencePointM = null;
  }

  snapshot() {
    return {
      anchorPointM: this.referencePointM === null ? null : [...this.referencePointM],
      stableSamples: this.samples.length,
    };
  }

  observe(target, nowMs) {
    if (!Number.isFinite(nowMs)) {
      return { accepted: false, reason: 'target_observation_invalid', ...this.snapshot() };
    }
    const pointM = target?.preview?.pointM;
    const usable = target?.depthValid === true && vector3(pointM) &&
      Number.isSafeInteger(target.preview.stableSamples) &&
      target.preview.stableSamples >= this.requiredStableSamples &&
      Number.isFinite(target.observedAtMs) && nowMs >= target.observedAtMs &&
      nowMs - target.observedAtMs <= this.maxAgeMs;
    if (!usable) {
      return { accepted: false, reason: 'no_fresh_depth_target', ...this.snapshot() };
    }
    if (target.preview.previewId === this.lastPreviewId) {
      return { accepted: false, reason: 'duplicate_vision_frame', ...this.snapshot() };
    }
    this.lastPreviewId = target.preview.previewId;
    this.samples.push([...pointM]);
    if (this.samples.length > this.stableWindow) this.samples.shift();
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

