'use strict';

const MAX_DISTANCE_CM = 10;
const WORKSPACE_M = Object.freeze([[0.15, 0.66], [-0.65, 0.45], [0.04, 0.65]]);

function normalizeCameraXStep(params) {
  if (!params || typeof params !== 'object' || Array.isArray(params) ||
      Object.keys(params).sort().join(',') !== 'action,axis,direction,distanceCm' ||
      params.action !== 'end_effector.step' || params.axis !== 'camera_x' ||
      !['left', 'right'].includes(params.direction) ||
      typeof params.distanceCm !== 'number' ||
      !Number.isFinite(params.distanceCm) ||
      params.distanceCm <= 0 || params.distanceCm > MAX_DISTANCE_CM) {
    return { ok: false, reason: '镜头 X 轴平移需要明确方向及 0～10 厘米的距离' };
  }
  return { ok: true, params: { ...params } };
}

function mountRotation(mount) {
  const matrix = mount?.T_flange_camera?.matrix_4x4 ?? mount?.matrix_4x4;
  if (!Array.isArray(matrix) || matrix.length !== 4 ||
      matrix.some(row => !Array.isArray(row) || row.length !== 4 ||
        row.some(value => typeof value !== 'number' || !Number.isFinite(value)))) {
    return null;
  }
  const columns = [0, 1, 2].map(index => matrix.slice(0, 3).map(row => row[index]));
  for (const column of columns) {
    if (Math.abs(Math.hypot(...column) - 1) > 0.02) return null;
  }
  for (let index = 0; index < 3; index++) {
    for (let next = index + 1; next < 3; next++) {
      if (Math.abs(columns[index].reduce((sum, value, axis) =>
        sum + value * columns[next][axis], 0)) > 0.02) return null;
    }
  }
  const [x, y, z] = columns;
  const determinant = (x[1] * y[2] - x[2] * y[1]) * z[0] +
    (x[2] * y[0] - x[0] * y[2]) * z[1] +
    (x[0] * y[1] - x[1] * y[0]) * z[2];
  if (determinant < 0.98 || determinant > 1.02 ||
      matrix[3].some((value, index) => Math.abs(value - (index === 3 ? 1 : 0)) > 1e-6)) {
    return null;
  }
  return matrix.slice(0, 3).map(row => row.slice(0, 3));
}

function rotateRpy(vector, [roll, pitch, yaw]) {
  const [cr, sr, cp, sp, cy, sy] = [
    Math.cos(roll), Math.sin(roll), Math.cos(pitch),
    Math.sin(pitch), Math.cos(yaw), Math.sin(yaw),
  ];
  const [x, y, z] = vector;
  return [
    cy * cp * x + (cy * sp * sr - sy * cr) * y + (cy * sp * cr + sy * sr) * z,
    sy * cp * x + (sy * sp * sr + cy * cr) * y + (sy * sp * cr - cy * sr) * z,
    -sp * x + cp * sr * y + cp * cr * z,
  ];
}

function cameraXTarget(state, params, mount) {
  const checked = normalizeCameraXStep(params);
  if (!checked.ok) return checked;
  const position = state?.flangePositionM;
  const euler = state?.flangeEulerRad;
  if (!Array.isArray(position) || position.length !== 3 ||
      !Array.isArray(euler) || euler.length !== 3 ||
      [...position, ...euler].some(value => typeof value !== 'number' || !Number.isFinite(value))) {
    return { ok: false, reason: '缺少新鲜的 SDK 法兰位置或姿态' };
  }
  const rotation = mountRotation(mount);
  if (!rotation) return { ok: false, reason: '镜头到法兰的旋转标定缺失或无效' };
  const cameraXInFlange = rotation.map(row => row[0]);
  const cameraXInBase = rotateRpy(cameraXInFlange, euler);
  const sign = params.direction === 'left' ? -1 : 1;
  const stepM = sign * params.distanceCm / 100;
  const target = position.map((value, index) => value + stepM * cameraXInBase[index]);
  if (target.some((value, index) =>
    value < WORKSPACE_M[index][0] || value > WORKSPACE_M[index][1])) {
    return { ok: false, reason: '目标超出末端位置允许范围' };
  }
  return {
    ok: true,
    position: target,
    euler: [...euler],
    displacementM: target.map((value, index) => value - position[index]),
    cameraMountId: mount.camera?.camera_mount_id ?? mount.camera_mount_id ?? null,
  };
}

module.exports = { MAX_DISTANCE_CM, WORKSPACE_M, normalizeCameraXStep, cameraXTarget };
