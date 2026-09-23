'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { planAlignmentStep, planWristStep } = require('../../../apps/web/src/active-depth/candidate');

const identity4 = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
const limits = {
  jointLimitsDeg: [[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],
  maxStepDeg: 2, maxCumulativeJointDeg: 10,
  maxCameraStepM: 0.005, maxCameraCumulativeM: 0.02,
};
const jointsDeg = [0,0,0,0,0,0];

function yRotation(degrees) {
  const angle = degrees*Math.PI/180;
  return [[Math.cos(angle),0,Math.sin(angle)],[0,1,0],[-Math.sin(angle),0,Math.cos(angle)]];
}

function plan(poseForJoints, extras = {}) {
  return planWristStep({ targetPixel: [562,327], jointsDeg,
    startJointsDeg: jointsDeg, tFlangeCamera: identity4,
    poseForJoints, limits, ...extras });
}

test('fisheye direction yields bounded J5 candidate without moving J1-J3', () => {
  const result = plan(joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) }));
  assert.equal(result.ok, true, result.reason);
  assert.deepEqual(result.targetJointsDeg.slice(0,3), [0,0,0]);
  assert.ok(result.targetJointsDeg[4] > 0);
  assert.ok(result.targetJointsDeg[4] <= 2);
  assert.equal(result.pixelEstimateKind, 'rotation_only_bearing');
  assert.ok(result.cameraShiftM <= 0.005);
  assert.ok(result.angularErrorRad < result.initialAngularErrorRad);
});

test('camera-center translation exceeding step bound is rejected', () => {
  const result = plan(joints => ({ positionM: joints.slice(3).some(Boolean) ? [0.006,0,0] : [0,0,0],
    rotation: yRotation(joints[4]) }));
  assert.deepEqual(result, { ok: false, reason: 'camera_step_limit' });
});

test('no modelled improvement does not trigger a wrist sweep', () => {
  const result = plan(() => ({ positionM: [0,0,0], rotation: yRotation(0) }));
  assert.deepEqual(result, { ok: false, reason: 'not_reachable_by_wrist' });
});

test('cumulative wrist budget is enforced before proposal', () => {
  const result = plan(joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) }),
    { startJointsDeg: [0,0,0,0,-10,0] });
  assert.ok(result.ok === false || Math.abs(result.targetJointsDeg[4] + 10) <= 10);
});

test('invalid FK pose and already-exceeded wrist budget fail closed', () => {
  assert.deepEqual(plan(() => ({ positionM: [0,0,0], rotation: [[NaN,0,0],[0,1,0],[0,0,1]] })),
    { ok: false, reason: 'invalid_fk_pose' });
  assert.deepEqual(plan(joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) }),
    { startJointsDeg: [0,0,0,11,0,0] }),
    { ok: false, reason: 'wrist_budget_exceeded' });
});

test('out-of-limit current joint state is not repaired by a proposal', () => {
  assert.deepEqual(plan(joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) }),
    { jointsDeg: [0,0,0,0,101,0], startJointsDeg: [0,0,0,0,101,0] }),
    { ok: false, reason: 'joint_state_out_of_limits' });
});

function align(poseForJoints, extras = {}) {
  return planAlignmentStep({
    targetPixel: [562,327], jointsDeg, startJointsDeg: jointsDeg,
    tFlangeCamera: identity4, poseForJoints,
    limits: { ...limits, maxArmStepDeg: 1, maxArmCumulativeJointDeg: 5 },
    completedSteps: 0, elapsedMs: 0, ...extras,
  });
}

test('alignment hierarchy always chooses an improving wrist candidate before arm', () => {
  const result = align(joints => ({
    positionM: [0,0,0], rotation: yRotation(joints[0]*4+joints[4]),
  }));
  assert.equal(result.ok, true, result.reason);
  assert.equal(result.tier, 'wrist');
  assert.equal(result.wristExhausted, false);
  assert.deepEqual(result.targetJointsDeg.slice(0,3), jointsDeg.slice(0,3));
});

test('arm fallback is used only after all wrist candidates are exhausted', () => {
  const result = align(joints => ({
    positionM: [0,0,0], rotation: yRotation(joints[0]*4),
  }));
  assert.equal(result.ok, true, result.reason);
  assert.equal(result.tier, 'arm_fallback');
  assert.equal(result.wristExhausted, true);
  assert.deepEqual(result.targetJointsDeg.slice(3), jointsDeg.slice(3));
  assert.ok(Math.abs(result.jointDeltasDeg[0]) <= 1);
});

test('measured wrist stagnation can explicitly force arm fallback', () => {
  const result = align(joints => ({
    positionM: [0,0,0], rotation: yRotation(joints[0]*4+joints[4]),
  }), { forceArmFallback: true });
  assert.equal(result.ok, true, result.reason);
  assert.equal(result.tier, 'arm_fallback');
  assert.equal(result.wristExhausted, true);
  assert.deepEqual(result.targetJointsDeg.slice(3), jointsDeg.slice(3));
});

test('alignment hierarchy fails closed at session and camera bounds', () => {
  const pose = joints => ({ positionM: [0,0,0], rotation: yRotation(joints[4]) });
  assert.deepEqual(align(pose, { completedSteps: 20 }), { ok: false, reason: 'step_limit' });
  assert.deepEqual(align(pose, { elapsedMs: 90000 }), { ok: false, reason: 'time_limit' });
  const shifting = joints => ({
    positionM: joints.some(Boolean) ? [0.021,0,0] : [0,0,0],
    rotation: yRotation(joints[0]+joints[4]),
  });
  assert.equal(align(shifting).ok, false);
});
