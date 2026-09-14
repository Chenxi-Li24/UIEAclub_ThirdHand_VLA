'use strict';

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function reliableGeometry(target) {
  const preview = target?.preview;
  return target?.depthValid === true && preview &&
    vector3(preview.pointM) && vector3(preview.pregraspPointM) &&
    vector3(preview.retreatPointM) &&
    Number.isSafeInteger(preview.stableSamples) && preview.stableSamples >= 5;
}

class LockedTargetMemory {
  constructor() {
    this.reset();
  }

  reset() {
    this.targets = new Map();
  }

  observe(targets) {
    for (const target of Array.isArray(targets) ? targets : []) {
      if (Number.isSafeInteger(target?.identityId) && reliableGeometry(target)) {
        if (!this.targets.has(target.identityId)) this.targets.set(target.identityId, new Map());
        const previews = this.targets.get(target.identityId);
        previews.set(target.preview.previewId, target);
        while (previews.size > 32) previews.delete(previews.keys().next().value);
      }
    }
  }

  targetFor(identityId, currentTarget, previewId = null) {
    if (!Number.isSafeInteger(identityId) ||
        currentTarget?.identityId !== identityId) return currentTarget ?? null;
    if (reliableGeometry(currentTarget) &&
        (previewId === null || currentTarget.preview.previewId === previewId)) return currentTarget;
    const previews = this.targets.get(identityId);
    const remembered = previewId === null
      ? previews && [...previews.values()].at(-1)
      : previews?.get(previewId);
    if (!remembered) return currentTarget;
    // Geometry/depth came from the stable acquisition frame. Freshness and
    // identity confirmation come from the current RGB track.
    return {
      ...remembered,
      observedAtMs: currentTarget.observedAtMs,
      identityConfirmed: true,
      armStationary: currentTarget.armStationary,
      calibrationValidated: currentTarget.calibrationValidated,
      safetyApproved: currentTarget.safetyApproved,
    };
  }
}

module.exports = { LockedTargetMemory, reliableGeometry };
