'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const { HomeCoordinator } = require(
  '../../../src/thirdhand_va/action/safety/home_coordinator'
);

const HOME = [0, 15, -30, 5, 0, 0];
const STARTUP_RANGES = [
  [-5, 5], [10, 20], [-35, -25], [0, 10], [-5, 5], [-5, 5],
];

function harness({ jointsDeg = [1, 15, -30, 5, 0, 0], startupValidated = true } = {}) {
  const robot = new EventEmitter();
  const commands = [];
  let state = {
    connected: true, healthy: true, stateFresh: true, stationary: true,
    jointsDeg: [...jointsDeg],
  };
  robot.getRobotState = () => ({ ...state, jointsDeg: [...state.jointsDeg] });
  robot.send = command => { commands.push(command); return true; };
  const coordinator = new HomeCoordinator({
    robotClient: robot,
    homePreset: 'home',
    homeJointsDeg: HOME,
    toleranceDeg: 0.5,
    startupValidated,
    startupJointRangesDeg: STARTUP_RANGES,
    timeoutMs: 1000,
    idFactory: () => 'startup-home-1',
  });
  return {
    coordinator,
    commands,
    setState(next) { state = { ...state, ...next }; },
    emit(event) { robot.emit('event', event); },
  };
}

test('startup already at Home becomes ready without issuing motion', () => {
  const h = harness({ jointsDeg: HOME });

  assert.equal(h.coordinator.start().accepted, true);
  assert.equal(h.coordinator.snapshot().phase, 'ready');
  assert.equal(h.coordinator.ready, true);
  assert.deepEqual(h.commands, []);
  h.coordinator.shutdown();
});

test('startup already measured at Home needs no motion-route approval', () => {
  const h = harness({ jointsDeg: HOME, startupValidated: false });

  assert.equal(h.coordinator.start().accepted, true);
  assert.equal(h.coordinator.snapshot().phase, 'ready');
  assert.equal(h.coordinator.ready, true);
  assert.deepEqual(h.commands, []);
  h.coordinator.shutdown();
});

test('startup away from Home commands one preset and waits for measured proof', () => {
  const h = harness();

  assert.equal(h.coordinator.start().accepted, true);
  assert.deepEqual(h.commands, [{
    cmd: 'preset', name: 'home', source: 'startup:return_home',
    request_id: 'startup-home-1',
  }]);
  assert.equal(h.coordinator.ready, false);
  assert.equal(h.coordinator.snapshot().phase, 'homing');

  h.emit({
    type: 'command_complete', command: 'preset', request_id: 'startup-home-1',
    reached: true, robot_healthy: true, actualJointsDeg: [...HOME],
  });
  assert.equal(h.coordinator.ready, true);
  assert.equal(h.coordinator.snapshot().phase, 'ready');
  h.coordinator.shutdown();
});

test('startup Home motion fails closed without physical approval or joint proof', () => {
  const unapproved = harness({ startupValidated: false });
  assert.deepEqual(unapproved.coordinator.start(), {
    accepted: false, reason: 'startup_home_not_validated',
  });
  assert.deepEqual(unapproved.commands, []);
  unapproved.coordinator.shutdown();

  const missed = harness();
  missed.coordinator.start();
  missed.emit({
    type: 'command_complete', command: 'preset', request_id: 'startup-home-1',
    reached: true, robot_healthy: true,
    actualJointsDeg: [0, 15, -30, 5, 0, 0.6],
  });
  assert.equal(missed.coordinator.ready, false);
  assert.equal(missed.coordinator.snapshot().phase, 'failed');
  assert.equal(missed.coordinator.snapshot().reason, 'home_not_verified');
  missed.coordinator.shutdown();
});

test('startup Home never moves from a joint pose outside the physically validated range', () => {
  const h = harness({ jointsDeg: [6, 15, -30, 5, 0, 0] });

  assert.deepEqual(h.coordinator.start(), {
    accepted: false, reason: 'startup_pose_outside_validated_range',
  });
  assert.deepEqual(h.commands, []);
  h.coordinator.shutdown();
});

test('startup Home timeout requires a proved software stop before terminal failure', async () => {
  const robot = new EventEmitter();
  const commands = [];
  const ids = ['startup-home-timeout', 'startup-home-stop'];
  robot.getRobotState = () => ({
    connected: true, healthy: true, stateFresh: true, stationary: true,
    jointsDeg: [1, 15, -30, 5, 0, 0],
  });
  robot.stopProofMode = 'cleanup_ack_only';
  robot.send = command => { commands.push(command); return true; };
  const coordinator = new HomeCoordinator({
    robotClient: robot, homePreset: 'home', homeJointsDeg: HOME,
    toleranceDeg: 0.5, startupValidated: true, timeoutMs: 5,
    stopAckTimeoutMs: 50,
    startupJointRangesDeg: STARTUP_RANGES,
    idFactory: () => ids.shift(),
  });

  coordinator.start();
  await new Promise(resolve => setTimeout(resolve, 15));

  assert.equal(commands[0].cmd, 'preset');
  assert.deepEqual(commands[1], {
    cmd: 'software_stop', source: 'startup:return_home_timeout',
    reason: 'startup_home_timeout', request_id: 'startup-home-stop',
  });
  assert.equal(coordinator.snapshot().phase, 'stopping');
  robot.emit('event', {
    type: 'command_complete', command: 'software_stop',
    request_id: 'startup-home-stop', cleanupAcknowledged: true,
    cleanupConfirmationMode: 'vendor_cleanup_returned',
    controlReleased: true, depowerIndependentlyConfirmed: false,
  });
  assert.equal(coordinator.snapshot().phase, 'failed');
  assert.equal(coordinator.snapshot().reason, 'startup_home_timeout');
  coordinator.shutdown();
});
