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
      > Math.min(20, limits.maxCumulativeJointDeg))) {
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
        const stepDeg = Math.min(4, limits.maxStepDeg) * scale;
        const targetJointsDeg = [...jointsDeg];
        targetJointsDeg[jointIndex] += sign*stepDeg;
        const [minimum, maximum] = limits.jointLimitsDeg[jointIndex];
        if (targetJointsDeg[jointIndex] < minimum || targetJointsDeg[jointIndex] > maximum
            || Math.abs(targetJointsDeg[jointIndex]-startJointsDeg[jointIndex])
              > Math.min(20, limits.maxCumulativeJointDeg)) continue;
        let proposed;
        try { proposed = cameraPose(poseForJoints(targetJointsDeg), tFlangeCamera); }
        catch { continue; }
        if (![...proposed.positionM, ...proposed.rotation.flat()].every(Number.isFinite)) continue;
        const cameraShiftM = distance(current.positionM, proposed.positionM);
        if (cameraShiftM > Math.min(0.01, limits.maxCameraStepM)
            || distance(start.positionM, proposed.positionM)
              > Math.min(0.04, limits.maxCameraCumulativeM)) {
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

function workspaceAllows(positionM, workspaceBoundsM) {
  if (workspaceBoundsM === undefined) return true;
  return Array.isArray(workspaceBoundsM) && workspaceBoundsM.length === 3
    && workspaceBoundsM.every((bounds, index) => Array.isArray(bounds)
      && bounds.length === 2 && bounds.every(Number.isFinite)
      && positionM[index] >= bounds[0] && positionM[index] <= bounds[1]);
}

function planAlignmentStep({ targetPixel, jointsDeg, startJointsDeg, tFlangeCamera,
  poseForJoints = forwardKinematicsFlangePose, limits, completedSteps = 0,
  elapsedMs = 0, workspaceBoundsM, forceArmFallback = false } = {}) {
  if (!Number.isInteger(completedSteps) || completedSteps < 0
      || !Number.isFinite(elapsedMs) || elapsedMs < 0) {
    return { ok: false, reason: 'invalid_session_state' };
  }
  if (completedSteps >= 20) return { ok: false, reason: 'step_limit' };
  if (elapsedMs >= 90000) return { ok: false, reason: 'time_limit' };
  if (!validJoints(jointsDeg) || !validJoints(startJointsDeg) || !validMount(tFlangeCamera)
      || !validLimits(limits) || typeof poseForJoints !== 'function') {
    return { ok: false, reason: 'invalid_model_input' };
  }
  if (jointsDeg.some((value, index) => value < limits.jointLimitsDeg[index][0]
      || value > limits.jointLimitsDeg[index][1])) {
    return { ok: false, reason: 'joint_state_out_of_limits' };
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
  let cameraLimitSeen = false;

  const rankTier = (indices, stepSizes, cumulativeLimitDeg) => {
    let best = null;
    for (const jointIndex of indices) {
      for (const sign of [1, -1]) {
        for (const stepDeg of stepSizes) {
          const targetJointsDeg = [...jointsDeg];
          targetJointsDeg[jointIndex] += sign * stepDeg;
          const [minimum, maximum] = limits.jointLimitsDeg[jointIndex];
          if (targetJointsDeg[jointIndex] < minimum || targetJointsDeg[jointIndex] > maximum
              || Math.abs(targetJointsDeg[jointIndex] - startJointsDeg[jointIndex])
                > cumulativeLimitDeg + 1e-9) continue;
          let proposed;
          try { proposed = cameraPose(poseForJoints(targetJointsDeg), tFlangeCamera); }
          catch { continue; }
          if (![...proposed.positionM, ...proposed.rotation.flat()].every(Number.isFinite)) continue;
          const cameraShiftM = distance(current.positionM, proposed.positionM);
          const cameraCumulativeM = distance(start.positionM, proposed.positionM);
          if (cameraShiftM > Math.min(0.01, limits.maxCameraStepM)
              || cameraCumulativeM > Math.min(0.04, limits.maxCameraCumulativeM)
              || !workspaceAllows(proposed.positionM, workspaceBoundsM)) {
            cameraLimitSeen = true;
            continue;
          }
          const proposedRay = transposeRotate(proposed.rotation, bearingBase);
          const angularErrorRad = angularError(proposedRay, desired.ray);
          if (initialAngularErrorRad - angularErrorRad < 0.001
              || (best && angularErrorRad >= best.angularErrorRad - 1e-12)) continue;
          const projection = rayToStreamPixel(proposedRay);
          if (!projection.ok) continue;
          best = {
            ok: true, targetJointsDeg, predictedPixel: projection.pixel,
            pixelEstimateKind: 'rotation_only_bearing', angularErrorRad,
            initialAngularErrorRad, cameraShiftM, cameraCumulativeM,
            jointDeltasDeg: targetJointsDeg.map((value, index) => value - jointsDeg[index]),
          };
        }
      }
    }
    return best;
  };

  if (!forceArmFallback) {
    const wristStep = Math.min(4, limits.maxStepDeg);
    const wrist = rankTier([3, 4, 5], [wristStep, Math.min(1, wristStep),
      Math.min(0.5, wristStep), Math.min(0.25, wristStep)],
    Math.min(20, limits.maxCumulativeJointDeg));
    if (wrist) return { ...wrist, tier: 'wrist', wristExhausted: false };
  }

  const armStep = Math.min(2, limits.maxArmStepDeg || 2);
  const arm = rankTier([0, 1, 2], [armStep, Math.min(0.5, armStep),
    Math.min(0.25, armStep)], Math.min(10, limits.maxArmCumulativeJointDeg || 10));
  if (arm) return { ...arm, tier: 'arm_fallback', wristExhausted: true };
  return { ok: false, reason: cameraLimitSeen ? 'camera_limit' : 'not_reachable' };
}

module.exports = { planAlignmentStep, planWristStep };
