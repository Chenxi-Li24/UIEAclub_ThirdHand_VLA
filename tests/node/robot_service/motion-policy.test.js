const test = require('node:test');
const assert = require('node:assert/strict');

const {
  DEFAULT_JOINT_LIMITS_DEG,
  DEFAULT_MAX_SPEEDS_DEG_S,
  validateJointTarget,
  isAccidentalZeroTarget,
  moveTimeFor,
} = require('../../../services/robot/src/motion-policy');

test('validates joint count, finite values, and every configured limit', () => {
  assert.equal(validateJointTarget([0, 0]).code, 'joint_count');
  assert.equal(validateJointTarget([0, 0, -20, 0, Number.NaN, 0]).code, 'joint_not_finite');

  DEFAULT_JOINT_LIMITS_DEG.forEach(([minimum, maximum], index) => {
    const below = [0, 0, -20, 0, 0, 0];
    below[index] = minimum - 0.01;
    assert.equal(validateJointTarget(below).code, 'joint_limit');

    const above = [0, 0, -20, 0, 0, 0];
    above[index] = maximum + 0.01;
    assert.equal(validateJointTarget(above).code, 'joint_limit');
  });

  assert.deepEqual(
    validateJointTarget([0, 7.6, -20, 0, 0, 0]),
    { ok: true, joints: [0, 7.6, -20, 0, 0, 0] },
  );
});

test('rejects accidental zero except explicit home preset', () => {
  const current = [20, 10, -30, 5, 0, 0];
  assert.equal(isAccidentalZeroTarget([0, 0, 0, 0, 0, 0], current, 'servo'), true);
  assert.equal(isAccidentalZeroTarget([0, 0, 0, 0, 0, 0], current, 'preset:home'), false);
  assert.equal(isAccidentalZeroTarget([0, 0, 0, 0, 0, 0], null, 'servo'), false);
  assert.equal(isAccidentalZeroTarget([0, 0, -1, 0, 0, 0], current, 'servo'), false);
});

test('computes bounded duration without exceeding hard joint speeds', () => {
  const current = [0, 0, -20, 0, 0, 0];
  const target = [30, 0, -20, 0, 0, 0];

  assert.equal(
    moveTimeFor(target, current, DEFAULT_MAX_SPEEDS_DEG_S, {
      speedScale: 0.05,
      minMoveTimeSec: 0.5,
      maxMoveTimeSec: 30,
    }),
    2,
  );

  assert.equal(
    moveTimeFor(current, current, DEFAULT_MAX_SPEEDS_DEG_S, {
      speedScale: 0.05,
      minMoveTimeSec: 0.5,
      maxMoveTimeSec: 30,
    }),
    0.5,
  );
});
