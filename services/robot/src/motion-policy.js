'use strict';

const DEFAULT_JOINT_LIMITS_DEG = Object.freeze([
  Object.freeze([-162, 162]),
  Object.freeze([-12, 201]),
  Object.freeze([-183, 0]),
  Object.freeze([-98, 98]),
  Object.freeze([-98, 98]),
  Object.freeze([-164, 164]),
]);

const DEFAULT_MAX_SPEEDS_DEG_S = Object.freeze([300, 300, 300, 1000, 1000, 1000]);

function validateJointTarget(joints, limits = DEFAULT_JOINT_LIMITS_DEG) {
  if (!Array.isArray(joints) || joints.length !== limits.length) {
    return { ok: false, code: 'joint_count', message: 'joint target must contain J1-J6' };
  }

  const normalized = joints.map(Number);
  for (let index = 0; index < normalized.length; index += 1) {
    const value = normalized[index];
    if (!Number.isFinite(value)) {
      return {
        ok: false,
        code: 'joint_not_finite',
        message: `J${index + 1} must be finite`,
      };
    }

    const [minimum, maximum] = limits[index];
    if (value < minimum || value > maximum) {
      return {
        ok: false,
        code: 'joint_limit',
        joint: index + 1,
        minimum,
        maximum,
        value,
        message: `J${index + 1} outside [${minimum}, ${maximum}] deg`,
      };
    }
  }

  return { ok: true, joints: normalized };
}

function isAccidentalZeroTarget(target, current, source = 'servo') {
  if (source === 'preset:home') return false;
  if (!Array.isArray(target) || target.length !== 6) return false;
  if (!Array.isArray(current) || current.length !== 6) return false;
  if (![...target, ...current].every(value => Number.isFinite(Number(value)))) return false;

  return target.every(value => Math.abs(Number(value)) < 0.05)
    && current.some(value => Math.abs(Number(value)) > 2);
}

function moveTimeFor(target, current, maxSpeeds = DEFAULT_MAX_SPEEDS_DEG_S, options = {}) {
  const {
    speedScale = 0.05,
    minMoveTimeSec = 0.5,
    maxMoveTimeSec = 30,
  } = options;

  if (![target, current, maxSpeeds].every(values => (
    Array.isArray(values)
    && values.length === 6
    && values.every(value => Number.isFinite(Number(value)))
  ))) {
    throw new TypeError('target, current, and maxSpeeds must contain six finite values');
  }
  if (!Number.isFinite(speedScale) || speedScale <= 0 || speedScale > 1) {
    throw new RangeError('speedScale must be within (0, 1]');
  }

  const deltas = target.map((value, index) => Math.abs(Number(value) - Number(current[index])));
  const hardMinimum = Math.max(
    ...deltas.map((delta, index) => delta / Number(maxSpeeds[index])),
  );
  const requested = Math.max(
    ...deltas.map((delta, index) => delta / (Number(maxSpeeds[index]) * speedScale)),
  );
  const bounded = Math.max(minMoveTimeSec, Math.min(maxMoveTimeSec, requested));
  return Math.max(hardMinimum, bounded);
}

module.exports = {
  DEFAULT_JOINT_LIMITS_DEG,
  DEFAULT_MAX_SPEEDS_DEG_S,
  validateJointTarget,
  isAccidentalZeroTarget,
  moveTimeFor,
};
