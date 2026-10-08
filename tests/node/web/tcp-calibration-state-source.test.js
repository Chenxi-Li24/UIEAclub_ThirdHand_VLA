'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { EventEmitter } = require('node:events');

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
    async sendTeachCommand(command) { sent.push(structuredClone(command)); return {accepted:true}; },
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

test('live stability consumes feedback events, remains stable across reads and resets on transition', async () => {
  const h=harness();
  const client=Object.assign(new EventEmitter(),h.client);
  const source=new TcpCalibrationRobotStateSource({client,confirmPoseStability:true});
  for(let i=0;i<=20;i++) {
    const s=canonicalState({moving:false,teachActive:false,stationary:false,streamId:'a',
      jointsDeg:[0,0,0,0,0,0],stateSequence:i+1,producerMonotonicNs:1e9+i*5e7});
    h.setState(s);client.emit('robot_state',s);
  }
  for(let i=0;i<5;i++)assert.equal(source.snapshot().locked,false);
  await source.teach('teach_hold');assert.equal(source.snapshot().locked,true);
  assert.equal(source.snapshot().reason,'pose_not_stable');
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

test('lost transport is resubscribed without sending hardware commands and stops on close',async()=>{
 const {source,client,sent}=harness(null);
 client.ws=null;
 source.connect();
 await new Promise(resolve=>setTimeout(resolve,1100));
 const calls=client.connectCalls;
 source.close();
 assert.ok(calls>=2);
 assert.deepEqual(sent,[]);
 await new Promise(resolve=>setTimeout(resolve,1100));
 assert.equal(client.connectCalls,calls);
});

test('state source constructs only bounded safety and teach commands', async () => {
  const { source, sent } = harness();
  assert.equal(source.softwareStop(), true);
  assert.deepEqual(sent, [{ cmd: 'software_stop', request_id: 'stop-1' }]);
  assert.equal(await source.teach('teach_start'), true);
  assert.equal(await source.teach('move_joint'), false);
  assert.deepEqual(sent[1], { cmd: 'teach_start', request_id: 'stop-1' });
  assert.equal(source.send, undefined);
  assert.equal(sent.some(command => ['move_l', 'servo', 'preset', 'gripper'].includes(command.cmd)), false);
});
