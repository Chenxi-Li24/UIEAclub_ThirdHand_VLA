'use strict';

const assert = require('assert/strict');
const { RobotStationarityTracker } = require('../robot-stationarity');

const tracker = new RobotStationarityTracker();
const stableJoints = [6.43, -11.81, -0.58, 32.99, -5.61, -4.49];
const noisyIdleVelocity = [0.11, 0.34, 0.11, 1.26, 0.42, -0.42];

assert.equal(tracker.update({
  jointsDeg: stableJoints,
  velocitiesDegS: noisyIdleVelocity,
  robotState: 'IDLE',
  motionActive: false,
  observedAtMs: 1000,
}), false);
assert.equal(tracker.update({
  jointsDeg: stableJoints.map((value, index) => value + (index % 2 ? 0.01 : -0.01)),
  velocitiesDegS: noisyIdleVelocity,
  robotState: 'IDLE',
  motionActive: false,
  observedAtMs: 1050,
}), false);
assert.equal(tracker.update({
  jointsDeg: stableJoints,
  velocitiesDegS: noisyIdleVelocity,
  robotState: 'IDLE',
  motionActive: false,
  observedAtMs: 1100,
}), true, 'stable joint positions must tolerate quantized SDK idle velocity');

assert.equal(tracker.update({
  jointsDeg: stableJoints.map((value, index) => value + (index === 3 ? 0.3 : 0)),
  velocitiesDegS: noisyIdleVelocity,
  robotState: 'IDLE',
  motionActive: false,
  observedAtMs: 1150,
}), false, 'measured joint displacement must revoke stationary state');

assert.equal(tracker.update({
  jointsDeg: stableJoints,
  velocitiesDegS: Array(6).fill(0),
  robotState: 'MOVING',
  motionActive: false,
  observedAtMs: 1200,
}), false, 'robot MOVING state must fail closed');

assert.equal(tracker.update({
  jointsDeg: stableJoints,
  velocitiesDegS: Array(6).fill(3),
  robotState: 'IDLE',
  motionActive: false,
  observedAtMs: 1250,
}), false, 'large reported velocity must fail closed');

console.log('robot stationarity smoke test passed');
