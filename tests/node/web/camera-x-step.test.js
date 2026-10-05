'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeCameraXStep, cameraXTarget } = require('../../../apps/web/src/language/camera-x-step');

const mount = {
  camera: { camera_mount_id: 'test-camera' },
  T_flange_camera: { matrix_4x4: [
    [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
  ] },
};
const state = { flangePositionM: [0.4, 0, 0.25], flangeEulerRad: [0, 0, 0] };
const step = (direction, distanceCm) => ({
  action: 'end_effector.step', axis: 'camera_x', direction, distanceCm,
});

test('camera image left and right translate by signed centimetres', () => {
  const left = cameraXTarget(state, step('left', 2), mount);
  const right = cameraXTarget(state, step('right', 2), mount);
  assert.equal(left.ok, true);
  assert.ok(Math.abs(left.position[0] - 0.38) < 1e-12);
  assert.ok(Math.abs(right.position[0] - 0.42) < 1e-12);
  assert.deepEqual(left.euler, [0, 0, 0]);
  assert.equal(left.timeSec, undefined, "target geometry must not choose Cartesian speed");
});

test('camera image X is rotated into the current base frame', () => {
  const turned = cameraXTarget(
    { flangePositionM: [0.4, 0, 0.25], flangeEulerRad: [0, 0, Math.PI / 2] },
    step('left', 2), mount,
  );
  assert.equal(turned.ok, true);
  assert.ok(Math.abs(turned.position[0] - 0.4) < 1e-12);
  assert.ok(Math.abs(turned.position[1] + 0.02) < 1e-12);
});

test('reject vague, excessive, unmeasured and workspace-exiting moves', () => {
  assert.equal(normalizeCameraXStep(step('left', 0)).ok, false);
  assert.equal(normalizeCameraXStep(step('left', 10.1)).ok, false);
  assert.equal(normalizeCameraXStep(step('left', NaN)).ok, false);
  assert.equal(cameraXTarget(state, step('left', 1), {}).ok, false);
  const reflected = { T_flange_camera: { matrix_4x4: [
    [-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
  ] } };
  assert.equal(cameraXTarget(state, step('left', 1), reflected).ok, false);
  assert.equal(cameraXTarget(
    { flangePositionM: [0.151, 0, 0.25], flangeEulerRad: [0, 0, 0] },
    step('left', 2), mount,
  ).ok, false);
});
