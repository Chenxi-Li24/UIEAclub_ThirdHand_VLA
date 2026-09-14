'use strict';

const { VisualTargetLock } = require('./visual-target-lock');
const {
  DepthObservationFilter,
  medianPoint,
  distance,
} = require('./depth-observation-filter');

class BaseFrameTargetLock {
  constructor(options = {}) {
    this.visual = new VisualTargetLock();
    this.depth = new DepthObservationFilter(options);
    this.anchorPointM = null;
  }

  reset() {
    this.visual.reset();
    this.depth.resetReference();
    this.anchorPointM = null;
  }

  // The wrist camera has moved. Its depth estimate needs a fresh local
  // reference, while the RGB/SAM2 identity remains the same physical bottle.
  resetEvidence() {
    this.depth.resetReference();
  }

  snapshot() {
    return {
      ...this.visual.snapshot(),
      ...this.depth.snapshot(),
      anchorPointM: this.anchorPointM === null ? null : [...this.anchorPointM],
    };
  }

  observe(targets, nowMs) {
    let identity = this.visual.snapshot().locked
      ? this.visual.track(targets)
      : this.visual.acquire(targets);
    // A forced RGB reacquisition can publish one transient tracker ID before
    // SAM2 settles. Before any world anchor exists (and before robot motion),
    // rebind to the sole selected candidate and restart depth evidence. Once
    // anchored, identity is immutable for the rest of the pick.
    if (identity.accepted !== true && this.anchorPointM === null &&
        identity.reason === 'locked_visual_target_missing') {
      this.visual.reset();
      this.depth.resetReference();
      identity = this.visual.acquire(targets);
    }
    if (identity.accepted !== true) {
      return { accepted: false, reason: identity.reason, ...this.snapshot() };
    }

    // Bottles are static during a pick.  Once depth has established a stable
    // robot-base point, freeze that world point for the rest of the session.
    // RGB keeps confirming the exact object identity while the wrist camera
    // moves; unreliable close-range depth must not move the goal post.
    if (this.anchorPointM !== null) {
      return { accepted: true, reason: null, target: identity.target,
        pointM: [...this.anchorPointM], measurementSource: 'cached_depth',
        ...this.snapshot() };
    }

    const measured = this.depth.observe(identity.target, nowMs);
    if (measured.accepted !== true) {
      return { accepted: false, reason: measured.reason, target: identity.target,
        ...this.snapshot() };
    }
    this.anchorPointM = [...measured.pointM];
    return { accepted: true, reason: null, target: identity.target,
      pointM: [...this.anchorPointM], spreadM: measured.spreadM,
      measurementSource: 'depth', ...this.snapshot() };
  }
}

module.exports = { BaseFrameTargetLock, medianPoint, distance };
