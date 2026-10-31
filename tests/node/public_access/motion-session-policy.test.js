'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const modulePath = path.resolve(__dirname, '../../../services/robot/src/motion-session-policy.js');
let policy;
try { policy = require(modulePath); } catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND' || !error.message.includes(modulePath)) throw error;
}
function validate(input) {
  assert.equal(typeof policy?.validateMotionSessionTarget, 'function', 'a bounded motion-session validator must exist');
  return policy.validateMotionSessionTarget(input);
}
function gripper(input) {
  assert.equal(typeof policy?.validateMotionSessionGripper, 'function', 'gripper scope must be checked independently of joint degrees');
  return policy.validateMotionSessionGripper(input);
}
function fixture() {
  const now = 1793449700000;
  const context = {
    deviceId: '11111111-1111-4111-8111-111111111111',
    bootId: '22222222-2222-4222-8222-222222222222',
    executorEpoch: '33333333-3333-4333-8333-333333333333',
    connectionId: '44444444-4444-4444-8444-444444444444',
    certificateId: '55555555-5555-4555-8555-555555555555',
    sessionId: '66666666-6666-4666-8666-666666666666',
    administratorId: '77777777-7777-4777-8777-777777777777',
    leaseId: '88888888-8888-4888-8888-888888888888',
    leaseEpoch: 3,
    hardwareFingerprint: 'a'.repeat(64),
  };
  // Synthetic commissioning data exercises policy only; these are not measured
  // hardware settings or an approval for any real device/planner.
  const limitsProfile = {
    schema: 1, version: 'synthetic-profile-v1', coordinateVersion: 'synthetic-frame-v1',
    verificationSource: 'local-commissioning', verified: true,
    evidenceId: 'synthetic:commissioning-evidence',
    jointLimitsDeg: [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
    maxSpeedDegS: [5, 5, 5, 5, 5, 5], maxAccelerationDegS2: [10, 10, 10, 10, 10, 10],
    stationarySpeedDegS: [0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
    minMoveTimeSec: 0.5, maxMoveTimeSec: 30,
    trajectoryBounds: {verified: true, evidenceId: 'synthetic:trajectory-bounds',
      peakVelocityFactor: 2, peakAccelerationFactor: 6, monotonicJointInterpolation: true},
    gripper: null,
  };
  // The fallback lets the first RED run fail as missing behavior assertions,
  // rather than ending at a module loader error before the cases can run.
  limitsProfile.digest = policy?.computeLimitsProfileDigest?.(limitsProfile) || 'b'.repeat(64);
  const baselineDeg = [10, 10, -20, 10, 10, 10];
  const scope = {...context, issuedAt: now - 2000, expiresAt: now + 60000,
    baselineDeg, baselineSequence: 100, baselineCapturedAt: now - 2020,
    maxDeltaDeg: 20, limitsDigest: limitsProfile.digest, gripperRange: null};
  const currentState = {...context, sourceMode: 'hardware', sdkConnected: true, stateReady: true,
    moving: false, capturedAt: now - 10, sequence: 110,
    jointsDeg: [...baselineDeg], velocitiesDegS: [0, 0, 0, 0, 0, 0]};
  return {scope, currentState, targetDeg: [12, 12, -22, 12, 12, 12], timeSec: 2, limitsProfile, now};
}

test('accepts a fresh six-joint request only within a trusted explicitly bounded session', () => {
  assert.deepEqual(validate(fixture()), {ok: true, code: 'MOTION_SCOPE_VALID'});
});

test('enforces the original baseline across successive small moves and the 20 degree ceiling', () => {
  const input = fixture();
  input.currentState.jointsDeg[0] = 29;
  input.targetDeg[0] = 30;
  assert.equal(validate(input).ok, true);
  input.targetDeg[0] = 30.001;
  assert.equal(validate(input).code, 'MOTION_SCOPE_DELTA_EXCEEDED');
  input.scope.maxDeltaDeg = 20.001;
  assert.equal(validate(input).code, 'INVALID_MOTION_SCOPE');
});

test('rejects an expired or future scope and a baseline that was already stale when accepted', () => {
  for (const [change, code] of [
    [i => { i.scope.expiresAt = i.now; }, 'MOTION_SCOPE_EXPIRED'],
    [i => { i.scope.issuedAt = i.now + 1; }, 'MOTION_SCOPE_NOT_YET_VALID'],
    [i => { i.scope.baselineCapturedAt = i.scope.issuedAt - 501; }, 'INVALID_MOTION_BASELINE'],
  ]) { const input = fixture(); change(input); assert.equal(validate(input).code, code); }
});

test('binds device, execution instance, certificate, human session and the exact lease', () => {
  for (const key of ['deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId',
    'sessionId', 'administratorId', 'leaseId', 'hardwareFingerprint', 'leaseEpoch']) {
    const input = fixture();
    input.currentState[key] = key === 'leaseEpoch' ? 4 : key === 'hardwareFingerprint' ? 'c'.repeat(64) : '99999999-9999-4999-8999-999999999999';
    assert.equal(validate(input).code, 'WRONG_MOTION_CONTEXT', key);
  }
});

test('requires current real connected stationary measured state at most 500 ms old', () => {
  for (const [change, code] of [
    [i => { i.currentState.capturedAt = i.now - 501; }, 'ROBOT_STATE_STALE'],
    [i => { i.currentState.capturedAt = i.now + 1; }, 'ROBOT_STATE_STALE'],
    [i => { i.currentState.sequence = 99; }, 'ROBOT_STATE_STALE'],
    [i => { i.currentState.sourceMode = 'simulation'; }, 'ROBOT_STATE_UNAVAILABLE'],
    [i => { i.currentState.sdkConnected = false; }, 'ROBOT_STATE_UNAVAILABLE'],
    [i => { i.currentState.stateReady = false; }, 'ROBOT_STATE_UNAVAILABLE'],
    [i => { i.currentState.moving = true; }, 'ROBOT_NOT_STATIONARY'],
    [i => { i.currentState.velocitiesDegS[2] = 0.101; }, 'ROBOT_NOT_STATIONARY'],
  ]) { const input = fixture(); change(input); assert.equal(validate(input).code, code); }
  const boundary = fixture(); boundary.currentState.capturedAt = boundary.now - 500;
  assert.equal(validate(boundary).ok, true);
});

test('rejects missing axes, sparse arrays, strings, NaN and nonfinite target values without coercion', () => {
  for (const value of [[1, 2], new Array(6), ['12', 12, -22, 12, 12, 12],
    [12, 12, -22, Number.NaN, 12, 12], [12, 12, -22, 12, Infinity, 12]]) {
    const input = fixture(); input.targetDeg = value;
    assert.equal(validate(input).code, 'INVALID_MOTION_TARGET');
  }
});

test('does not widen the J2 limit for the old readable -12.21 degree sample', () => {
  const baseline = fixture(); baseline.scope.baselineDeg[1] = -12.21;
  assert.equal(validate(baseline).code, 'BASELINE_OUTSIDE_LIMITS');
  const state = fixture(); state.currentState.jointsDeg[1] = -12.21;
  assert.equal(validate(state).code, 'ROBOT_STATE_OUTSIDE_LIMITS');
  const target = fixture(); target.targetDeg[1] = -12.21; target.scope.baselineDeg[1] = -5;
  assert.equal(validate(target).code, 'MOTION_TARGET_OUTSIDE_LIMITS');
});

test('detects changed bounds even when the caller retained the old claimed profile digest', () => {
  const input = fixture(); input.limitsProfile.jointLimitsDeg[1][0] = -13;
  assert.equal(validate(input).code, 'LIMITS_PROFILE_DIGEST_MISMATCH');
  const scope = fixture(); scope.scope.limitsDigest = 'c'.repeat(64);
  assert.equal(validate(scope).code, 'LIMITS_PROFILE_DIGEST_MISMATCH');
});

test('does not accept profiles or trajectory envelopes without commissioning evidence', () => {
  for (const change of [
    i => { i.limitsProfile.verified = false; },
    i => { i.limitsProfile.verificationSource = 'browser'; },
    i => { i.limitsProfile.evidenceId = ''; },
    i => { i.limitsProfile.trajectoryBounds.verified = false; },
    i => { i.limitsProfile.trajectoryBounds.monotonicJointInterpolation = false; },
  ]) { const input = fixture(); change(input); assert.equal(validate(input).code, 'LIMITS_PROFILE_UNVERIFIED'); }
});

test('rejects invalid durations and checks peak speed and acceleration instead of only average speed', () => {
  for (const duration of [undefined, '2', 0, -1, 0.49, 31, Infinity, Number.NaN]) {
    const input = fixture(); input.timeSec = duration;
    assert.equal(validate(input).code, 'INVALID_MOTION_DURATION');
  }
  const speed = fixture(); speed.timeSec = 0.5;
  // Average=4 deg/s is below 5, but the verified bound gives peak=8.
  assert.equal(validate(speed).code, 'MOTION_SPEED_EXCEEDED');
  const acceleration = fixture(); acceleration.timeSec = 1;
  assert.equal(validate(acceleration).code, 'MOTION_ACCELERATION_EXCEEDED');
});

test('fails closed on missing scope, malformed metadata and unverified measured positions', () => {
  const missing = fixture(); missing.scope = null;
  assert.equal(validate(missing).code, 'MOTION_SCOPE_REQUIRED');
  for (const change of [
    i => { i.scope.leaseEpoch = 0; },
    i => { i.scope.administratorId = ''; },
    i => { i.scope.baselineSequence = -1; },
    i => { i.scope.maxDeltaDeg = 0; },
  ]) { const input = fixture(); change(input); assert.equal(validate(input).code, 'INVALID_MOTION_SCOPE'); }
  const unknown = fixture(); unknown.currentState.jointsDeg[0] = null;
  assert.equal(validate(unknown).code, 'ROBOT_STATE_UNAVAILABLE');
});

test('never converts joint-degree permission into a gripper percentage', () => {
  const input = fixture(); input.targetPosition = 0.2;
  assert.equal(gripper(input).code, 'GRIPPER_SCOPE_REQUIRED');
  input.scope.gripperRange = {unit: 'normalized', baselinePosition: 0.4, minimum: 0.35, maximum: 0.45, maxDelta: 0.05};
  assert.equal(gripper(input).code, 'GRIPPER_PROFILE_UNVERIFIED');
});

test('validates an explicitly commissioned gripper range in its own unit and velocity envelope', () => {
  const input = fixture();
  input.scope.gripperRange = {unit: 'normalized', baselinePosition: 0.4, minimum: 0.35, maximum: 0.45, maxDelta: 0.05};
  input.limitsProfile.gripper = {unit: 'normalized', verified: true, evidenceId: 'synthetic:gripper-only',
    minimum: 0, maximum: 1, maxSpeedPerSec: 0.1, maxAccelerationPerSec2: 0.2, stationarySpeedPerSec: 0.001,
    trajectoryBounds: {verified: true, evidenceId: 'synthetic:gripper-envelope', peakVelocityFactor: 2, peakAccelerationFactor: 6, monotonicJointInterpolation: true}};
  input.limitsProfile.digest = policy?.computeLimitsProfileDigest?.(input.limitsProfile) || 'b'.repeat(64);
  input.scope.limitsDigest = input.limitsProfile.digest;
  input.currentState.gripperPosition = 0.4; input.currentState.gripperVelocityPerSec = 0;
  input.targetPosition = 0.42;
  assert.deepEqual(gripper(input), {ok: true, code: 'GRIPPER_SCOPE_VALID'});
  input.targetPosition = 0.6;
  assert.equal(gripper(input).code, 'GRIPPER_SCOPE_DELTA_EXCEEDED');
  input.targetPosition = 0.42; input.scope.gripperRange.unit = 'degrees';
  assert.equal(gripper(input).code, 'INVALID_GRIPPER_SCOPE');
});

test('validation is pure and never changes the baseline, profile or target', () => {
  const input = fixture(), before = JSON.stringify(input);
  assert.equal(validate(input).ok, true);
  assert.equal(JSON.stringify(input), before);
});

test('malformed top-level requests fail closed without a thrown exception', () => {
  for (const input of [null, false, 4, 'move', []]) {
    assert.deepEqual(validate(input), {ok: false, code: 'MOTION_SCOPE_REQUIRED'});
    assert.deepEqual(gripper(input), {ok: false, code: 'MOTION_SCOPE_REQUIRED'});
  }
});

test('an already escaped measured position cannot be used as permission to move back', () => {
  const input = fixture(); input.currentState.jointsDeg[0] = 30.01;
  assert.equal(validate(input).code, 'ROBOT_STATE_OUTSIDE_SCOPE');
});

test('does not skip holes in source velocities or profile joint limits', () => {
  const state = fixture(); delete state.currentState.velocitiesDegS[0];
  assert.equal(validate(state).code, 'ROBOT_STATE_UNAVAILABLE');
  const profile = fixture(); delete profile.limitsProfile.jointLimitsDeg[3];
  assert.equal(validate(profile).code, 'INVALID_LIMITS_PROFILE');
});
