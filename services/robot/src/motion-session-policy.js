'use strict';
const {createHash} = require('node:crypto');

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const DIGEST = /^[a-f0-9]{64}$/;
const CONTEXT_IDS = ['deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId',
  'sessionId', 'administratorId', 'leaseId'];
const CONTEXT = [...CONTEXT_IDS, 'leaseEpoch', 'hardwareFingerprint'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const finite = value => typeof value === 'number' && Number.isFinite(value);
const positive = value => finite(value) && value > 0;
const sequence = value => Number.isSafeInteger(value) && value >= 0;
const timestamp = value => Number.isSafeInteger(value) && value >= 0;
const reference = value => typeof value === 'string' && value.length > 0 && value.length <= 256
  && !/[\x00-\x20\x7f]/.test(value);
const six = value => Array.isArray(value) && value.length === 6
  && Array.from({length: 6}, (_, index) => Object.hasOwn(value, index) && finite(value[index])).every(Boolean);
const failure = (code, joint) => ({ok: false, code, ...(joint === undefined ? {} : {joint})});

function envelopeProjection(bounds) {
  if (!object(bounds)) return null;
  return {verified: bounds.verified, evidenceId: bounds.evidenceId,
    peakVelocityFactor: bounds.peakVelocityFactor, peakAccelerationFactor: bounds.peakAccelerationFactor,
    monotonicJointInterpolation: bounds.monotonicJointInterpolation};
}

function profileProjection(profile) {
  const gripper = profile.gripper;
  return {
    schema: profile.schema, version: profile.version, coordinateVersion: profile.coordinateVersion,
    verificationSource: profile.verificationSource, verified: profile.verified, evidenceId: profile.evidenceId,
    jointLimitsDeg: profile.jointLimitsDeg, maxSpeedDegS: profile.maxSpeedDegS,
    maxAccelerationDegS2: profile.maxAccelerationDegS2, stationarySpeedDegS: profile.stationarySpeedDegS,
    minMoveTimeSec: profile.minMoveTimeSec, maxMoveTimeSec: profile.maxMoveTimeSec,
    trajectoryBounds: envelopeProjection(profile.trajectoryBounds),
    gripper: object(gripper) ? {unit: gripper.unit, verified: gripper.verified, evidenceId: gripper.evidenceId,
      minimum: gripper.minimum, maximum: gripper.maximum, maxSpeedPerSec: gripper.maxSpeedPerSec,
      maxAccelerationPerSec2: gripper.maxAccelerationPerSec2, stationarySpeedPerSec: gripper.stationarySpeedPerSec,
      trajectoryBounds: envelopeProjection(gripper.trajectoryBounds)} : gripper,
  };
}

/** Digest every field this policy uses, in a fixed order. No claimed digest is hashed. */
function computeLimitsProfileDigest(profile) {
  if (!object(profile)) throw new TypeError('Commissioned limits profile required');
  return createHash('sha256').update(JSON.stringify(profileProjection(profile))).digest('hex');
}

function verifiedEnvelope(bounds) {
  return object(bounds) && bounds.verified === true && reference(bounds.evidenceId)
    && positive(bounds.peakVelocityFactor) && bounds.peakVelocityFactor >= 1
    && positive(bounds.peakAccelerationFactor) && bounds.monotonicJointInterpolation === true;
}

function validateProfile(profile) {
  if (!object(profile) || profile.verified !== true || profile.verificationSource !== 'local-commissioning'
    || !reference(profile.evidenceId) || !verifiedEnvelope(profile.trajectoryBounds)) {
    return failure('LIMITS_PROFILE_UNVERIFIED');
  }
  if (profile.schema !== 1 || !reference(profile.version) || !reference(profile.coordinateVersion)
    || !Array.isArray(profile.jointLimitsDeg) || profile.jointLimitsDeg.length !== 6
    || !Array.from({length: 6}, (_, index) => {
      const limits = profile.jointLimitsDeg[index];
      return Array.isArray(limits) && limits.length === 2 && finite(limits[0]) && finite(limits[1]) && limits[0] < limits[1];
    }).every(Boolean)
    || !six(profile.maxSpeedDegS) || !profile.maxSpeedDegS.every(positive)
    || !six(profile.maxAccelerationDegS2) || !profile.maxAccelerationDegS2.every(positive)
    || !six(profile.stationarySpeedDegS) || !profile.stationarySpeedDegS.every((v, i) => positive(v) && v <= profile.maxSpeedDegS[i])
    || !finite(profile.minMoveTimeSec) || profile.minMoveTimeSec < 0.5
    || !finite(profile.maxMoveTimeSec) || profile.maxMoveTimeSec > 30 || profile.maxMoveTimeSec < profile.minMoveTimeSec) {
    return failure('INVALID_LIMITS_PROFILE');
  }
  if (!DIGEST.test(profile.digest || '') || profile.digest !== computeLimitsProfileDigest(profile)) {
    return failure('LIMITS_PROFILE_DIGEST_MISMATCH');
  }
  return null;
}

function outside(values, limits) {
  return values.findIndex((value, index) => value < limits[index][0] || value > limits[index][1]);
}

/**
 * Necessary local scope checks only. The caller must load scope/profile from
 * controlled commissioning state, never from a browser's claimed `verified`.
 * Authentication, signatures, lease ownership, physical binding, video, actual
 * planner bounds and Cartesian/collision checks remain separate prerequisites.
 * Success here is not a certificate that an SDK trajectory is physically safe.
 */
function validateCommon({scope, currentState, limitsProfile, now} = {}) {
  if (!object(scope)) return failure('MOTION_SCOPE_REQUIRED');
  if (!timestamp(now)) return failure('INVALID_MOTION_TIME');
  if (!CONTEXT_IDS.every(key => UUID.test(scope[key] || ''))
    || !Number.isSafeInteger(scope.leaseEpoch) || scope.leaseEpoch < 1 || !DIGEST.test(scope.hardwareFingerprint || '')
    || !timestamp(scope.issuedAt) || !timestamp(scope.expiresAt) || scope.expiresAt <= scope.issuedAt
    || !positive(scope.maxDeltaDeg) || scope.maxDeltaDeg > 20 || !sequence(scope.baselineSequence)) {
    return failure('INVALID_MOTION_SCOPE');
  }
  if (now < scope.issuedAt) return failure('MOTION_SCOPE_NOT_YET_VALID');
  if (now >= scope.expiresAt) return failure('MOTION_SCOPE_EXPIRED');
  if (!six(scope.baselineDeg) || !timestamp(scope.baselineCapturedAt)
    || scope.baselineCapturedAt > scope.issuedAt || scope.issuedAt - scope.baselineCapturedAt > 500) {
    return failure('INVALID_MOTION_BASELINE');
  }
  const profileError = validateProfile(limitsProfile);
  if (profileError) return profileError;
  if (scope.limitsDigest !== limitsProfile.digest) return failure('LIMITS_PROFILE_DIGEST_MISMATCH');
  if (!object(currentState) || !CONTEXT.every(key => currentState[key] === scope[key])) return failure('WRONG_MOTION_CONTEXT');
  if (currentState.sourceMode !== 'hardware' || currentState.sdkConnected !== true || currentState.stateReady !== true
    || !six(currentState.jointsDeg) || !six(currentState.velocitiesDegS)) return failure('ROBOT_STATE_UNAVAILABLE');
  if (!timestamp(currentState.capturedAt) || now - currentState.capturedAt < 0 || now - currentState.capturedAt > 500
    || currentState.capturedAt < scope.baselineCapturedAt || !sequence(currentState.sequence)
    || currentState.sequence < scope.baselineSequence) return failure('ROBOT_STATE_STALE');
  if (currentState.moving !== false
    || currentState.velocitiesDegS.some((v, i) => Math.abs(v) > limitsProfile.stationarySpeedDegS[i])) {
    return failure('ROBOT_NOT_STATIONARY');
  }
  const baselineOutside = outside(scope.baselineDeg, limitsProfile.jointLimitsDeg);
  if (baselineOutside !== -1) return failure('BASELINE_OUTSIDE_LIMITS', baselineOutside + 1);
  const stateOutside = outside(currentState.jointsDeg, limitsProfile.jointLimitsDeg);
  if (stateOutside !== -1) return failure('ROBOT_STATE_OUTSIDE_LIMITS', stateOutside + 1);
  // Feedback itself escaping the accepted volume also closes the session;
  // a nearby target is not permission to move back from an unknown state.
  const escaped = currentState.jointsDeg.findIndex((v, i) => Math.abs(v - scope.baselineDeg[i]) > scope.maxDeltaDeg);
  if (escaped !== -1) return failure('ROBOT_STATE_OUTSIDE_SCOPE', escaped + 1);
  return null;
}

function durationError(timeSec, profile) {
  return !finite(timeSec) || timeSec < profile.minMoveTimeSec || timeSec > profile.maxMoveTimeSec
    ? failure('INVALID_MOTION_DURATION') : null;
}

function validateMotionSessionTarget(input = {}) {
  if (!object(input)) return failure('MOTION_SCOPE_REQUIRED');
  const commonError = validateCommon(input);
  if (commonError) return commonError;
  const {scope, currentState, targetDeg, timeSec, limitsProfile} = input;
  if (!six(targetDeg)) return failure('INVALID_MOTION_TARGET');
  const targetOutside = outside(targetDeg, limitsProfile.jointLimitsDeg);
  if (targetOutside !== -1) return failure('MOTION_TARGET_OUTSIDE_LIMITS', targetOutside + 1);
  const scopeOutside = targetDeg.findIndex((v, i) => Math.abs(v - scope.baselineDeg[i]) > scope.maxDeltaDeg);
  if (scopeOutside !== -1) return failure('MOTION_SCOPE_DELTA_EXCEEDED', scopeOutside + 1);
  const badDuration = durationError(timeSec, limitsProfile);
  if (badDuration) return badDuration;
  for (let index = 0; index < 6; index++) {
    const delta = Math.abs(targetDeg[index] - currentState.jointsDeg[index]);
    const velocityBound = delta / timeSec * limitsProfile.trajectoryBounds.peakVelocityFactor;
    const accelerationBound = delta / timeSec ** 2 * limitsProfile.trajectoryBounds.peakAccelerationFactor;
    if (velocityBound > limitsProfile.maxSpeedDegS[index]) return failure('MOTION_SPEED_EXCEEDED', index + 1);
    if (accelerationBound > limitsProfile.maxAccelerationDegS2[index]) return failure('MOTION_ACCELERATION_EXCEEDED', index + 1);
  }
  return {ok: true, code: 'MOTION_SCOPE_VALID'};
}

function validateMotionSessionGripper(input = {}) {
  if (!object(input)) return failure('MOTION_SCOPE_REQUIRED');
  const commonError = validateCommon(input);
  if (commonError) return commonError;
  const {scope, currentState, targetPosition, timeSec, limitsProfile} = input;
  const range = scope.gripperRange;
  if (!object(range)) return failure('GRIPPER_SCOPE_REQUIRED');
  const profile = limitsProfile.gripper;
  if (!object(profile) || profile.verified !== true || !reference(profile.evidenceId)
    || !verifiedEnvelope(profile.trajectoryBounds)) return failure('GRIPPER_PROFILE_UNVERIFIED');
  if (!['normalized', 'mm'].includes(profile.unit) || !finite(profile.minimum) || !finite(profile.maximum)
    || profile.minimum >= profile.maximum || !positive(profile.maxSpeedPerSec)
    || !positive(profile.maxAccelerationPerSec2) || !positive(profile.stationarySpeedPerSec)
    || profile.stationarySpeedPerSec > profile.maxSpeedPerSec
    || profile.unit === 'normalized' && (profile.minimum < 0 || profile.maximum > 1)) return failure('INVALID_GRIPPER_PROFILE');
  if (range.unit !== profile.unit || !finite(range.minimum) || !finite(range.maximum) || range.minimum >= range.maximum
    || range.minimum < profile.minimum || range.maximum > profile.maximum
    || !finite(range.baselinePosition) || range.baselinePosition < range.minimum || range.baselinePosition > range.maximum
    || !positive(range.maxDelta) || range.maxDelta > profile.maximum - profile.minimum) return failure('INVALID_GRIPPER_SCOPE');
  if (!finite(currentState.gripperPosition) || !finite(currentState.gripperVelocityPerSec)) return failure('GRIPPER_STATE_UNAVAILABLE');
  if (Math.abs(currentState.gripperVelocityPerSec) > profile.stationarySpeedPerSec) return failure('GRIPPER_NOT_STATIONARY');
  if (currentState.gripperPosition < range.minimum || currentState.gripperPosition > range.maximum
    || Math.abs(currentState.gripperPosition - range.baselinePosition) > range.maxDelta) return failure('GRIPPER_STATE_OUTSIDE_SCOPE');
  if (!finite(targetPosition)) return failure('INVALID_GRIPPER_TARGET');
  if (targetPosition < range.minimum || targetPosition > range.maximum
    || Math.abs(targetPosition - range.baselinePosition) > range.maxDelta) return failure('GRIPPER_SCOPE_DELTA_EXCEEDED');
  const badDuration = durationError(timeSec, limitsProfile);
  if (badDuration) return badDuration;
  const delta = Math.abs(targetPosition - currentState.gripperPosition);
  if (delta / timeSec * profile.trajectoryBounds.peakVelocityFactor > profile.maxSpeedPerSec) return failure('GRIPPER_SPEED_EXCEEDED');
  if (delta / timeSec ** 2 * profile.trajectoryBounds.peakAccelerationFactor > profile.maxAccelerationPerSec2) return failure('GRIPPER_ACCELERATION_EXCEEDED');
  return {ok: true, code: 'GRIPPER_SCOPE_VALID'};
}

module.exports = {computeLimitsProfileDigest, validateMotionSessionTarget, validateMotionSessionGripper};
