'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const {
  TcpCalibrationRobotStateSource,
} = require('../../../apps/web/src/tcp-calibration/robot-state-source');

const POLICY = `sha256:${'a'.repeat(64)}`;

function canonicalState(overrides = {}) {
  return {
    connected: true,
    healthy: true,
    stationary: true,
    stateFresh: true,
    poseFrame: 'robot_flange',
    flangePositionM: [0.2, 0.3, 0.4],
    flangeEulerRad: [0, 0, 0],
    stateSequence: 7,
    producerMonotonicNs: 9_000_000,
    framePolicyId: POLICY,
    frameNormalization: {
      policyId: POLICY, sourcePoseFrame: 'sdk_tool', destinationPoseFrame: 'robot_flange',
    },
    sdkToolPose: { positionM: [0.37334, 0.3, 0.4], eulerRad: [0, 0, 0] },
    ...overrides,
  };
}

function harness(state = canonicalState()) {
  const sent = [];
  const client = {
    framePolicyId: POLICY,
    connectCalls: 0,
    closeCalls: 0,
    connect() { this.connectCalls += 1; return true; },
    shutdown() { this.closeCalls += 1; },
    getRobotState() { return state; },
    send(command) { sent.push(structuredClone(command)); return true; },
  };
  const source = new TcpCalibrationRobotStateSource({
    client,
    requestIdFactory: () => 'stop-1',
  });
  return { source, client, sent, setState(value) { state = value; } };
}

test('canonical snapshot exposes true flange matrix and SDK provenance once', () => {
  const { source } = harness();
  const snapshot = source.snapshot();
  assert.equal(snapshot.locked, false);
  assert.equal(snapshot.poseFrame, 'robot_flange');
  assert.equal(snapshot.framePolicyId, POLICY);
  assert.deepEqual(snapshot.TBaseFlange, [
    [1, 0, 0, 0.2], [0, 1, 0, 0.3], [0, 0, 1, 0.4], [0, 0, 0, 1],
  ]);
  assert.deepEqual(snapshot.sdkToolPose.positionM, [0.37334, 0.3, 0.4]);
  assert.throws(() => { snapshot.TBaseFlange[0][3] = 99; }, TypeError);
});

test('unavailable or noncanonical state remains locked', () => {
  const { source, setState } = harness(null);
  assert.deepEqual(source.snapshot(), {
    connected: false, locked: true, reason: 'robot_state_unavailable', framePolicyId: POLICY,
  });
  for (const state of [
    canonicalState({ poseFrame: 'sdk_tool' }),
    canonicalState({ framePolicyId: `sha256:${'b'.repeat(64)}` }),
    canonicalState({ frameNormalization: {} }),
  ]) {
    setState(state);
    assert.equal(source.snapshot().locked, true);
  }
});

test('lifecycle delegates without opening a socket during construction', () => {
  const { source, client } = harness();
  assert.equal(client.connectCalls, 0);
  assert.equal(source.connect(), true);
  source.close();
  assert.equal(client.connectCalls, 1);
  assert.equal(client.closeCalls, 1);
});

test('state source constructs only software_stop and exposes no generic send', () => {
  const { source, sent } = harness();
  assert.equal(source.softwareStop(), true);
  assert.deepEqual(sent, [{ cmd: 'software_stop', request_id: 'stop-1' }]);
  assert.equal(source.send, undefined);
  assert.equal(sent.some(command => ['move_l', 'servo', 'preset', 'gripper'].includes(command.cmd)), false);
});
