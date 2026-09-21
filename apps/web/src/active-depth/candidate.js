'use strict';

const { streamPixelToRay, rayToStreamPixel } = require('./fisheye');
const { forwardKinematicsFlangePose } = require('./flange-pose');

const ROI_CENTER = [315.5, 234];
const STEP_SCALES = [1, 0.5, 0.25, 0.125];

function rotate(rotation, vector) {
  return rotation.map(row => row.reduce((sum, value, index) => sum + value*vector[index], 0));
}

function transposeRotate(rotation, vector) {
  return rotation[0].map((unused, column) => rotation.reduce((sum, row, index) =>
    sum + row[column]*vector[index], 0));
}

function multiply(first, second) {
  return first.map(row => second[0].map((unused, column) =>
    row.reduce((sum, value, index) => sum + value*second[index][column], 0)));
}

function validJoints(joints) {
  return Array.isArray(joints) && joints.length === 6 && joints.every(Number.isFinite);
}

function validMount(matrix) {
  return Array.isArray(matrix) && matrix.length === 4
    && matrix.every(row => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite))
    && matrix[3][0] === 0 && matrix[3][1] === 0
    && matrix[3][2] === 0 && matrix[3][3] === 1;
}

function cameraPose(flange, matrix) {
  const mountRotation = matrix.slice(0,3).map(row => row.slice(0,3));
  const offset = matrix.slice(0,3).map(row => row[3]);
  const translated = rotate(flange.rotation, offset);
  return {
    positionM: flange.positionM.map((value, index) => value+translated[index]),
    rotation: multiply(flange.rotation, mountRotation),
  };
}

function distance(first, second) {
  return Math.hypot(...first.map((value, index) => value-second[index]));
}

function angularError(first, second) {
  const dot = first.reduce((sum, value, index) => sum + value*second[index], 0);
  return Math.acos(Math.min(1, Math.max(-1, dot)));
}

function validLimits(limits) {
  return limits && Array.isArray(limits.jointLimitsDeg) && limits.jointLimitsDeg.length === 6
    && limits.jointLimitsDeg.every(pair => Array.isArray(pair) && pair.length === 2
      && pair.every(Number.isFinite) && pair[0] < pair[1])
    && ['maxStepDeg','maxCumulativeJointDeg','maxCameraStepM','maxCameraCumulativeM']
      .every(key => Number.isFinite(limits[key]) && limits[key] > 0);
}

function planWristStep({ targetPixel, jointsDeg, startJointsDeg, tFlangeCamera,
  poseForJoints = forwardKinematicsFlangePose, limits } = {}) {
  if (!validJoints(jointsDeg) || !validJoints(startJointsDeg) || !validMount(tFlangeCamera)
      || !validLimits(limits) || typeof poseForJoints !== 'function') {
    return { ok: false, reason: 'invalid_model_input' };
  }
  if (jointsDeg.some((value, index) => value < limits.jointLimitsDeg[index][0]
      || value > limits.jointLimitsDeg[index][1])) {
    return { ok: false, reason: 'joint_state_out_of_limits' };
  }
  if ([3,4,5].some(index => Math.abs(jointsDeg[index]-startJointsDeg[index])
      > Math.min(10, limits.maxCumulativeJointDeg))) {
    return { ok: false, reason: 'wrist_budget_exceeded' };
  }
  const target = streamPixelToRay(targetPixel);
  const desired = streamPixelToRay(ROI_CENTER);
  if (!target.ok || !desired.ok) return { ok: false, reason: 'invalid_target_pixel' };
  let current;
  let start;
  try {
    current = cameraPose(poseForJoints(jointsDeg), tFlangeCamera);
    start = cameraPose(poseForJoints(startJointsDeg), tFlangeCamera);
  } catch {
    return { ok: false, reason: 'invalid_fk_pose' };
  }
  if (![...current.positionM, ...start.positionM,
    ...current.rotation.flat(), ...start.rotation.flat()].every(Number.isFinite)) {
    return { ok: false, reason: 'invalid_fk_pose' };
  }
  const bearingBase = rotate(current.rotation, target.ray);
  const initialAngularErrorRad = angularError(target.ray, desired.ray);
  let best = null;
  let cameraLimitSeen = false;
  for (const jointIndex of [3,4,5]) {
    for (const sign of [1,-1]) {
      for (const scale of STEP_SCALES) {
        const stepDeg = Math.min(2, limits.maxStepDeg) * scale;
        const targetJointsDeg = [...jointsDeg];
        targetJointsDeg[jointIndex] += sign*stepDeg;
        const [minimum, maximum] = limits.jointLimitsDeg[jointIndex];
        if (targetJointsDeg[jointIndex] < minimum || targetJointsDeg[jointIndex] > maximum
            || Math.abs(targetJointsDeg[jointIndex]-startJointsDeg[jointIndex])
              > Math.min(10, limits.maxCumulativeJointDeg)) continue;
        let proposed;
        try { proposed = cameraPose(poseForJoints(targetJointsDeg), tFlangeCamera); }
        catch { continue; }
        if (![...proposed.positionM, ...proposed.rotation.flat()].every(Number.isFinite)) continue;
        const cameraShiftM = distance(current.positionM, proposed.positionM);
        if (cameraShiftM > Math.min(0.005, limits.maxCameraStepM)
            || distance(start.positionM, proposed.positionM)
              > Math.min(0.02, limits.maxCameraCumulativeM)) {
          cameraLimitSeen = true;
          continue;
        }
        const proposedRay = transposeRotate(proposed.rotation, bearingBase);
        const angularErrorRad = angularError(proposedRay, desired.ray);
        if (angularErrorRad >= initialAngularErrorRad - 1e-9
            || (best && angularErrorRad >= best.angularErrorRad - 1e-12)) continue;
        const projection = rayToStreamPixel(proposedRay);
        if (!projection.ok) continue;
        best = { ok: true, targetJointsDeg, predictedPixel: projection.pixel,
          pixelEstimateKind: 'rotation_only_bearing', angularErrorRad,
          initialAngularErrorRad, cameraShiftM };
      }
    }
  }
  return best || { ok: false, reason: cameraLimitSeen
    ? 'camera_step_limit' : 'not_reachable_by_wrist' };
}

module.exports = { planWristStep };
