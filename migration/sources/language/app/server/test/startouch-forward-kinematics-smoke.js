'use strict';

const assert = require('assert/strict');
const { forwardKinematicsPosition } = require('../startouch-forward-kinematics');

function close(actual, expected, tolerance = 1e-9) {
  assert.equal(actual.length, expected.length);
  actual.forEach((value, index) => {
    assert(Math.abs(value - expected[index]) <= tolerance,
      `index ${index}: expected ${expected[index]}, got ${value}`);
  });
}

// Fixtures were generated independently from the checked-in URDF chain.
close(forwardKinematicsPosition([0, 0, 0, 0, 0, 0]), [
  0.28334, 0, 0.17605,
]);
close(forwardKinematicsPosition([0, 20, -20, 0, 0, 0]), [
  0.299321455492, 0, 0.266685337981,
]);
close(forwardKinematicsPosition([30, 40, -50, -10, 15, 25]), [
  0.245094770741, 0.195700530572, 0.478227628962,
]);
assert.throws(() => forwardKinematicsPosition([0, 0, 0]), /six finite joint angles/);
assert.throws(() => forwardKinematicsPosition([0, 0, 0, 0, 0, NaN]), /six finite joint angles/);

console.log('PASS Startouch forward kinematics fixtures');
