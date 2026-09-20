'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { evaluateHomeState } = require(
  '../../../src/thirdhand_va/action/safety/home_gate'
);

const HOME = [0, 15, -30, 5, 0, 0];

function robotState(overrides = {}) {
  return {
    connected: true,
    healthy: true,
    stateFresh: true,
    stationary: true,
    jointsDeg: [...HOME],
    ...overrides,
  };
}

test('home gate accepts only fresh stationary feedback inside every joint tolerance', () => {
  const result = evaluateHomeState({
    robotState: robotState({ jointsDeg: [0.2, 14.7, -29.6, 4.8, 0.1, -0.2] }),
    homeJointsDeg: HOME,
    toleranceDeg: 0.5,
  });

  assert.equal(result.allowed, true);
  assert.deepEqual(result.blockers, []);
  assert.equal(result.maxJointErrorDeg, 0.4);
});

test('home gate fails closed for stale, moving, missing, or out-of-tolerance feedback', () => {
  for (const [state, blocker] of [
    [robotState({ stateFresh: false }), 'robot_state_stale'],
    [robotState({ stationary: false }), 'robot_not_stationary'],
    [robotState({ jointsDeg: null }), 'robot_joint_state_invalid'],
    [robotState({ jointsDeg: [0, 15, -30, 5, 0, 0.6] }), 'robot_not_at_home'],
  ]) {
    const result = evaluateHomeState({
      robotState: state,
      homeJointsDeg: HOME,
      toleranceDeg: 0.5,
    });
    assert.equal(result.allowed, false);
    assert.equal(result.blockers.includes(blocker), true);
  }
});

test('home gate rejects an unconfigured Home instead of guessing one', () => {
  const result = evaluateHomeState({
    robotState: robotState(),
    homeJointsDeg: null,
    toleranceDeg: 0.5,
  });

  assert.deepEqual(result.blockers, ['home_definition_invalid']);
});
