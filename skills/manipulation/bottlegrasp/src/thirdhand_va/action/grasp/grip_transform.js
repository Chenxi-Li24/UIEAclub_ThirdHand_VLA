'use strict';

const EPSILON = 1e-6;

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function validateRigidTransform(matrix) {
  if (!Array.isArray(matrix) || matrix.length !== 4 ||
      matrix.some(row => !Array.isArray(row) || row.length !== 4 || !row.every(Number.isFinite))) {
    throw new TypeError('grip_transform_invalid');
  }
  if (new Set(matrix).size !== 4) throw new TypeError('grip_transform_rows_aliased');
  if (matrix[3].some((value, index) => Math.abs(value - (index === 3 ? 1 : 0)) > EPSILON)) {
    throw new TypeError('grip_transform_not_rigid');
  }
  const rotation = matrix.slice(0, 3).map(row => row.slice(0, 3));
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) {
      const dot = rotation.reduce((sum, row) => sum + row[i] * row[j], 0);
      if (Math.abs(dot - (i === j ? 1 : 0)) > EPSILON) {
        throw new TypeError('grip_transform_not_rigid');
      }
    }
  }
  const determinant =
    rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1]) -
    rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0]) +
    rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0]);
  if (Math.abs(determinant - 1) > EPSILON) throw new TypeError('grip_transform_not_rigid');
  return matrix.map(row => [...row]);
}

function multiply(left, right) {
  return left.map((row, i) => right[0].map((_, j) =>
    row.reduce((sum, value, k) => sum + value * right[k][j], 0)));
}

function invertRigid(matrix) {
  const transform = validateRigidTransform(matrix);
  const result = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 1]];
  for (let i = 0; i < 3; i += 1) {
    for (let j = 0; j < 3; j += 1) result[i][j] = transform[j][i];
    result[i][3] = -result[i].slice(0, 3).reduce(
      (sum, value, j) => sum + value * transform[j][3], 0);
  }
  return result;
}

function poseToMatrix(pose) {
  if (!vector3(pose?.positionM) || !vector3(pose?.eulerRad)) {
    throw new TypeError('grip_pose_invalid');
  }
  const [roll, pitch, yaw] = pose.eulerRad;
  const [cr, sr, cp, sp, cy, sy] =
    [Math.cos(roll), Math.sin(roll), Math.cos(pitch), Math.sin(pitch),
      Math.cos(yaw), Math.sin(yaw)];
  return [
    [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, pose.positionM[0]],
    [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, pose.positionM[1]],
    [-sp, cp * sr, cp * cr, pose.positionM[2]],
    [0, 0, 0, 1],
  ];
}

function matrixToPose(matrix) {
  const transform = validateRigidTransform(matrix);
  const pitch = Math.atan2(-transform[2][0], Math.hypot(transform[0][0], transform[1][0]));
  const roll = Math.atan2(transform[2][1], transform[2][2]);
  const yaw = Math.atan2(transform[1][0], transform[0][0]);
  return {
    positionM: transform.slice(0, 3).map(row => Number(row[3].toFixed(12))),
    eulerRad: [roll, pitch, yaw].map(value => Number(value.toFixed(12))),
  };
}

function gripTargetToFlangePose(gripPose, flangeToGrip) {
  return matrixToPose(multiply(poseToMatrix(gripPose), invertRigid(flangeToGrip)));
}

function flangeToGripPose(flangePose, flangeToGrip) {
  return matrixToPose(multiply(poseToMatrix(flangePose), validateRigidTransform(flangeToGrip)));
}

module.exports = { validateRigidTransform, gripTargetToFlangePose, flangeToGripPose };
