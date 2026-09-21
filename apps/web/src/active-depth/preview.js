'use strict';

const { planWristStep } = require('./candidate');
const { streamPixelToRay } = require('./fisheye');

const ROI = Object.freeze({ left: 203, top: 149, right: 428, bottom: 319 });
const MAX_AGE_MS = 300;
const LIMITS = Object.freeze({ maxStepDeg: 2, maxCumulativeJointDeg: 10,
  maxCameraStepM: 0.005, maxCameraCumulativeM: 0.02 });

function finiteJoints(joints) {
  return Array.isArray(joints) && joints.length === 6 && joints.every(Number.isFinite);
}

function fresh(timestamp, nowMs) {
  return Number.isFinite(timestamp) && timestamp <= nowMs
    && nowMs-timestamp <= MAX_AGE_MS;
}

function validMatrix(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 4
      || !matrix.every(row => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite))) {
    return false;
  }
  if (matrix[3].some((value, index) => value !== (index === 3 ? 1 : 0))) return false;
  const rows = matrix.slice(0,3).map(row => row.slice(0,3));
  for (let rowIndex = 0; rowIndex < 3; rowIndex += 1) {
    for (let otherIndex = 0; otherIndex < 3; otherIndex += 1) {
      const dot = rows[rowIndex].reduce((sum, value, index) =>
        sum + value*rows[otherIndex][index], 0);
      if (Math.abs(dot-(rowIndex === otherIndex ? 1 : 0)) > 0.01) return false;
    }
  }
  const determinant = rows[0][0]*(rows[1][1]*rows[2][2]-rows[1][2]*rows[2][1])
    - rows[0][1]*(rows[1][0]*rows[2][2]-rows[1][2]*rows[2][0])
    + rows[0][2]*(rows[1][0]*rows[2][1]-rows[1][1]*rows[2][0]);
  return Math.abs(determinant-1) <= 0.02;
}

function bearingError(pixel) {
  const measured = streamPixelToRay(pixel);
  const center = streamPixelToRay([315.5, 234]);
  if (!measured.ok || !center.ok) return Infinity;
  const dot = measured.ray.reduce((sum, value, index) => sum+value*center.ray[index], 0);
  return Math.acos(Math.min(1, Math.max(-1, dot)));
}

function buildActiveDepthPreview({ observation, robotSnapshot, mount, previousStep = null,
  nowMs = Date.now() } = {}) {
  const blockers = [];
  const selected = Number(observation?.selectedStableId);
  const targetId = Number.isSafeInteger(selected) && selected >= 1 && selected <= 5 ? selected : null;
  const matches = targetId === null ? [] : (observation?.targets || []).filter(item =>
    Number(item.stable_id ?? item.stableId) === targetId);
  const targetPixel = matches.length === 1 ? (matches[0].centroid_xy ?? matches[0].centroidXY) : null;
  const result = { mode: 'offline', executable: false, targetId, targetPixel,
    roi: ROI, proposal: null, blockers };

  if (observation?.frameId === null || observation?.frameId === undefined
      || !fresh(observation?.observedAtMs, nowMs)) blockers.push('vision_stale');
  if (targetId === null || matches.length !== 1 || !Array.isArray(targetPixel)
      || targetPixel.length !== 2 || !targetPixel.every(Number.isFinite)) {
    blockers.push('target_not_locked');
  }
  if (matches.length === 1 && matches[0].track_state !== undefined
      && matches[0].track_state !== 'confirmed') blockers.push('target_not_confirmed');
  if (!fresh(robotSnapshot?.observedAtMs, nowMs) || robotSnapshot?.stateName !== 'IDLE'
      || !finiteJoints(robotSnapshot?.jointsDeg)) blockers.push('robot_state_unavailable');
  if (!Array.isArray(robotSnapshot?.jointLimitsDeg) || robotSnapshot.jointLimitsDeg.length !== 6) {
    blockers.push('joint_limits_missing');
  }
  if (!validMatrix(mount?.matrix_4x4)) blockers.push('mount_invalid');
  if (mount?.physical_validation?.status !== 'approved') blockers.push('mount_unverified');
  if (!observation?.camera_mount_id || !observation?.registration_id) {
    blockers.push('camera_evidence_missing');
  } else if (observation.camera_mount_id !== mount?.camera_mount_id
      || observation.registration_id !== mount?.registration_id) {
    blockers.push('camera_evidence_mismatch');
  }
  if (previousStep) {
    if (previousStep.targetId !== targetId || !Number.isFinite(previousStep.completedAtMs)
        || observation?.observedAtMs <= previousStep.completedAtMs) {
      blockers.push('step_evidence_invalid');
    } else if (Array.isArray(previousStep.beforePixel) && Array.isArray(previousStep.predictedPixel)
        && Array.isArray(targetPixel)) {
      const observedDelta = targetPixel.map((value, index) => value-previousStep.beforePixel[index]);
      const predictedDelta = previousStep.predictedPixel.map((value, index) =>
        value-previousStep.beforePixel[index]);
      const dot = observedDelta.reduce((sum, value, index) => sum+value*predictedDelta[index], 0);
      if (!Number.isFinite(dot) || dot <= 0
          || bearingError(targetPixel) >= bearingError(previousStep.beforePixel)-1e-3) {
        blockers.push('response_inconsistent');
      }
    } else blockers.push('step_evidence_invalid');
    if (!finiteJoints(robotSnapshot?.startJointsDeg)) blockers.push('session_start_missing');
  }
  const hardBlockers = blockers.filter(item => item !== 'mount_unverified');
  if (hardBlockers.length) return result;
  const proposal = planWristStep({ targetPixel, jointsDeg: robotSnapshot.jointsDeg,
    startJointsDeg: robotSnapshot.startJointsDeg || robotSnapshot.jointsDeg,
    tFlangeCamera: mount.matrix_4x4,
    limits: { ...LIMITS, jointLimitsDeg: robotSnapshot.jointLimitsDeg } });
  if (proposal.ok) result.proposal = proposal;
  else blockers.push(proposal.reason);
  return result;
}

module.exports = { buildActiveDepthPreview };
