'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  validateRigidTransform,
  gripTargetToFlangePose,
  flangeToGripPose,
} = require('../../../src/thirdhand_va/action/grasp/grip_transform');

const flangeToGrip = [
  [1, 0, 0, 0.02],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
];

test('converts desired grip pose to flange pose in the rotating flange frame', () => {
  const desiredGrip = {
    positionM: [0.30, 0.10, 0.20],
    eulerRad: [0, 0, Math.PI / 2],
  };
  const flange = gripTargetToFlangePose(desiredGrip, flangeToGrip);
  assert.deepEqual(flange.positionM, [0.30, 0.08, 0.20]);
  assert.ok(Math.abs(flange.eulerRad[2] - Math.PI / 2) < 1e-12);
  const roundTrip = flangeToGripPose(flange, flangeToGrip);
  roundTrip.positionM.forEach((value, index) => {
    assert.ok(Math.abs(value - desiredGrip.positionM[index]) < 1e-12);
  });
});

test('rejects non-rigid or aliased transforms', () => {
  assert.throws(() => validateRigidTransform([
    [2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
  ]), /grip_transform_not_rigid/);
  assert.throws(() => validateRigidTransform([
    [-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
  ]), /grip_transform_not_rigid/);
  const row = [1, 0, 0, 0];
  assert.throws(() => validateRigidTransform([row, row, [0, 0, 1, 0], [0, 0, 0, 1]]),
    /grip_transform_rows_aliased/);
});
