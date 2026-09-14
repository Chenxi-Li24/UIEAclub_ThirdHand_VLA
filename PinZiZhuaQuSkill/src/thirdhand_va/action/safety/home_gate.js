'use strict';

function jointVector(value) {
  return Array.isArray(value) && value.length === 6 && value.every(Number.isFinite);
}

function validTolerance(value) {
  return Number.isFinite(value) && value > 0 && value <= 2.0;
}

function freezeResult(blockers, jointErrorsDeg = null) {
  const errors = jointErrorsDeg === null
    ? null : Object.freeze(jointErrorsDeg.map(value => Number(value.toFixed(12))));
  return Object.freeze({
    allowed: blockers.length === 0,
    blockers: Object.freeze([...blockers]),
    jointErrorsDeg: errors,
    maxJointErrorDeg: errors === null ? null : Math.max(...errors),
  });
}

function evaluateHomeJoints({ jointsDeg, homeJointsDeg, toleranceDeg } = {}) {
  if (!jointVector(homeJointsDeg) || !validTolerance(toleranceDeg)) {
    return freezeResult(['home_definition_invalid']);
  }
  if (!jointVector(jointsDeg)) return freezeResult(['robot_joint_state_invalid']);
  const errors = jointsDeg.map((value, index) => Math.abs(value - homeJointsDeg[index]));
  return freezeResult(
    errors.some(value => value > toleranceDeg) ? ['robot_not_at_home'] : [],
    errors,
  );
}

function evaluateHomeState({ robotState, homeJointsDeg, toleranceDeg } = {}) {
  if (!jointVector(homeJointsDeg) || !validTolerance(toleranceDeg)) {
    return freezeResult(['home_definition_invalid']);
  }
  const blockers = [];
  if (robotState?.connected !== true) blockers.push('robot_disconnected');
  if (robotState?.healthy !== true) blockers.push('robot_unhealthy');
  if (robotState?.stateFresh !== true) blockers.push('robot_state_stale');
  if (robotState?.stationary !== true) blockers.push('robot_not_stationary');
  const joints = evaluateHomeJoints({
    jointsDeg: robotState?.jointsDeg,
    homeJointsDeg,
    toleranceDeg,
  });
  for (const blocker of joints.blockers) blockers.push(blocker);
  return freezeResult([...new Set(blockers)], joints.jointErrorsDeg);
}

module.exports = { evaluateHomeJoints, evaluateHomeState };
