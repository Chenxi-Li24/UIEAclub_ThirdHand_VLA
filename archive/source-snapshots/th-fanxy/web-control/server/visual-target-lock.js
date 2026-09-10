'use strict';

function visualTarget(target) {
  return target && Number.isSafeInteger(target.identityId) && target.identityId >= 0;
}

class VisualTargetLock {
  constructor() {
    this.reset();
  }

  reset() {
    this.identityId = null;
  }

  snapshot() {
    return { locked: this.identityId !== null, identityId: this.identityId };
  }

  acquire(targets) {
    if (!Array.isArray(targets)) {
      return { accepted: false, reason: 'target_observation_invalid', ...this.snapshot() };
    }
    const candidates = targets.filter(visualTarget);
    if (candidates.length === 0) {
      return { accepted: false, reason: 'selected_visual_target_missing', ...this.snapshot() };
    }
    if (candidates.length !== 1) {
      return { accepted: false, reason: 'target_selection_ambiguous', ...this.snapshot() };
    }
    this.identityId = candidates[0].identityId;
    return { accepted: true, reason: null, target: candidates[0], ...this.snapshot() };
  }

  track(targets) {
    if (!Array.isArray(targets)) {
      return { accepted: false, reason: 'target_observation_invalid', ...this.snapshot() };
    }
    if (this.identityId === null) {
      return { accepted: false, reason: 'visual_target_not_locked', ...this.snapshot() };
    }
    const selected = targets.find(target =>
      visualTarget(target) && target.identityId === this.identityId
    );
    if (!selected) {
      return { accepted: false, reason: 'locked_visual_target_missing', ...this.snapshot() };
    }
    return { accepted: true, reason: null, target: selected, ...this.snapshot() };
  }
}

module.exports = { VisualTargetLock };

