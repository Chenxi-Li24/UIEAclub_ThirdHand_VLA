'use strict';

const assert = require('assert/strict');
const { materializeRefinement } = require('../active-view-motion-adapter');

const result = materializeRefinement({
  tcpPositionM: [0.267, -0.008, 0.080],
  tcpEulerRad: [-0.115, 0.359, 0.006],
  deltaBaseM: [-0.002, -0.016, -0.011],
  rotationDeltaBaseRad: [-0.021, 0.051, -0.067],
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
});
assert.deepEqual(result.position, [0.265, -0.024, 0.069]);
assert.deepEqual(result.euler, [-0.115, 0.359, 0.006]);
assert.deepEqual(result.rotationDeltaBaseRad, [-0.021, 0.051, -0.067]);
assert.ok(result.timeSec >= 2.0);

const rotationOnly = materializeRefinement({
  tcpPositionM: [0.267, -0.008, 0.080],
  tcpEulerRad: [-0.115, 0.359, 0.006],
  deltaBaseM: [0, 0, 0],
  rotationDeltaBaseRad: [0, 2 * Math.PI / 180, 0],
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
});
assert.deepEqual(rotationOnly.position, [0.267, -0.008, 0.080]);
assert.deepEqual(rotationOnly.rotationDeltaBaseRad, [0, 2 * Math.PI / 180, 0]);

assert.equal(materializeRefinement({
  tcpPositionM: [0.267, -0.008, 0.080],
  tcpEulerRad: [-0.115, 0.359, 0.006],
  deltaBaseM: [0.0201, 0, 0],
  rotationDeltaBaseRad: [0, 0, 0],
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
}), null);

assert.equal(materializeRefinement({
  tcpPositionM: [0.267, -0.008, 0.080],
  tcpEulerRad: [-0.115, 0.359, 0.006],
  deltaBaseM: [0.010, 0, 0],
  rotationDeltaBaseRad: [0, 0, 5.01 * Math.PI / 180],
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
}), null);

console.log('PASS active-view motion adapter preserves bounded vision deltas');
