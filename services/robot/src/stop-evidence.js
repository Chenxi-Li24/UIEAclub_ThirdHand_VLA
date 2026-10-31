'use strict';

// A semantic validator, not an authentication mechanism. Its caller must obtain
// evidence from a trusted local hardware-feedback adapter and the profile from
// the approved device configuration. SDK cleanup/connection flags never create
// this evidence. `depowered` applies only to the returned actuator coverage.
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const HASH = /^[a-f0-9]{64}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const positive = value => finite(value) && value > 0;
const vector = value => Array.isArray(value) && value.length === 6
  && [0, 1, 2, 3, 4, 5].every(index => Object.hasOwn(value, index) && finite(value[index]));
const reject = code => ({ ok: false, code });

function validateStopEvidence(evidence, currentContext, limitsProfile) {
  const profile = limitsProfile?.stop;
  if (!record(limitsProfile) || !DIGEST.test(limitsProfile.digest) || !record(profile)
      || !positive(profile.maxStopTimeMs)
      || !positive(profile.maxFeedbackAgeMs) || profile.maxFeedbackAgeMs > 500
      || !finite(profile.maxVelocityRadS) || profile.maxVelocityRadS < 0
      || !finite(profile.maxJointDeltaDeg) || profile.maxJointDeltaDeg < 0
      || !positive(profile.minStableDurationMs) || profile.minStableDurationMs > profile.maxStopTimeMs
      || !Number.isSafeInteger(profile.minSamples) || profile.minSamples < 2
      || typeof profile.requiresDisabled !== 'boolean' || typeof profile.includesGripper !== 'boolean'
      || profile.includesGripper && (!finite(profile.maxGripperVelocityMmS) || profile.maxGripperVelocityMmS < 0
        || !finite(profile.maxGripperDeltaMm) || profile.maxGripperDeltaMm < 0)) {
    return reject('STOP_PROFILE_REQUIRED');
  }
  if (!record(currentContext) || !UUID.test(currentContext.commandId)
      || !UUID.test(currentContext.executorEpoch) || !HASH.test(currentContext.hardwareFingerprint)
      || !Number.isSafeInteger(currentContext.now) || currentContext.now < 0) {
    return reject('STOP_CONTEXT_REQUIRED');
  }
  if (!record(evidence) || evidence.state !== 'stopped') return reject('STOP_UNCONFIRMED');
  if (evidence.commandId !== currentContext.commandId || evidence.executorEpoch !== currentContext.executorEpoch
      || evidence.hardwareFingerprint !== currentContext.hardwareFingerprint) return reject('WRONG_EXECUTOR');
  if (!Number.isSafeInteger(evidence.requestedAt) || !Number.isSafeInteger(evidence.observedAt)
      || evidence.requestedAt < 0 || evidence.observedAt < evidence.requestedAt
      || evidence.observedAt > currentContext.now
      || currentContext.now - evidence.observedAt > profile.maxFeedbackAgeMs
      || evidence.observedAt - evidence.requestedAt > profile.maxStopTimeMs) {
    return reject('STOP_EVIDENCE_STALE');
  }
  const measured = evidence.measurement;
  if (!record(measured) || measured.kind !== 'hardware_feedback' || measured.sourceMode !== 'hardware'
      || measured.profileDigest !== limitsProfile.digest
      || typeof evidence.reason !== 'string' || !/^[A-Z][A-Z0-9_]{0,79}$/.test(evidence.reason)
      || !vector(measured.jointVelocitiesRadS) || !vector(measured.jointDeltaDeg)
      || typeof measured.driversDisabled !== 'boolean') return reject('STOP_FEEDBACK_UNAVAILABLE');
  if (!Number.isSafeInteger(measured.sampleCount) || measured.sampleCount < profile.minSamples
      || !finite(measured.stableDurationMs) || measured.stableDurationMs < profile.minStableDurationMs
      || measured.stableDurationMs > evidence.observedAt - evidence.requestedAt
      || measured.jointVelocitiesRadS.some(value => Math.abs(value) > profile.maxVelocityRadS)
      || measured.jointDeltaDeg.some(value => Math.abs(value) > profile.maxJointDeltaDeg)) {
    return reject('STOP_NOT_STABLE');
  }
  if (profile.requiresDisabled && !measured.driversDisabled) return reject('DRIVER_STATE_UNCONFIRMED');
  if (profile.includesGripper && (!finite(measured.gripperVelocityMmS) || !finite(measured.gripperDeltaMm)
      || Math.abs(measured.gripperVelocityMmS) > profile.maxGripperVelocityMmS
      || Math.abs(measured.gripperDeltaMm) > profile.maxGripperDeltaMm)) return reject('GRIPPER_STOP_UNCONFIRMED');
  return { ok: true, code: 'STOP_VERIFIED', depowered: measured.driversDisabled,
    coverage: { joints: 6, gripper: profile.includesGripper } };
}

module.exports = { validateStopEvidence };
