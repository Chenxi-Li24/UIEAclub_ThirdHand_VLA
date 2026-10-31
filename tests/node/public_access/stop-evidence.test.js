'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const { RobotController } = require('../../../services/robot/src/robot-controller');
const { StartouchBridge } = require('../../../services/robot/src/startouch-bridge');

function stoppingController(config = {}) {
  const controller = new RobotController({ simulate: false, ...config });
  controller.bridge.connected = true;
  controller.bridge.softwareStop = () => true;
  const messages = [];
  controller.on('message', message => messages.push(message));
  const requestId = randomUUID();
  controller.handleCommand({ cmd: 'software_stop', request_id: requestId }, message => messages.push(message));
  return { controller, messages, requestId };
}

test('hardware cleanup and connection:false never claim measured stop or depowering', () => {
  const { controller, messages, requestId } = stoppingController();
  controller.bridge.emit('software_stop_complete', {
    connected: false, reason: 'software_stop', request_id: requestId,
    sdk_released: true, cleanup_state: 'completed', ts: Date.now(),
  });
  const result = messages.find(message => message.type === 'command_status');
  assert.equal(result.request_id, requestId);
  assert.equal(result.stopped, false);
  assert.equal(result.state, 'unknown');
  assert.equal(result.code, 'STOP_UNCONFIRMED');
  const stop = messages.find(message => message.type === 'software_stop');
  assert.equal(stop.complete, false);
  assert.equal(stop.depowered, false);
  assert.equal(stop.sdkReleased, true);
});

test('hardware timeout emits a correlated unknown result and clears its pending command', () => {
  const { controller, messages, requestId } = stoppingController();
  controller.bridge.emit('software_stop_timeout', { request_id: requestId, ts: Date.now() });
  const result = messages.find(message => message.type === 'command_status');
  assert.ok(result);
  assert.equal(result.request_id, requestId);
  assert.equal(result.stopped, false);
  assert.equal(result.state, 'unknown');
  assert.equal(result.code, 'STOP_UNCONFIRMED');
  assert.equal(controller.pendingLowLevel.has(requestId), false);
});

test('a second stop does not overwrite the outstanding command correlation', () => {
  const { controller, messages, requestId } = stoppingController();
  const second = randomUUID();
  controller.handleCommand({ cmd: 'software_stop', request_id: second }, message => messages.push(message));
  assert.equal(controller.pendingStopRequestId, requestId);
  assert.equal(controller.pendingLowLevel.has(second), false);
  assert.ok(messages.some(message => message.type === 'error' && message.code === 'stop_pending'));
});

test('SDK release receipt is emitted as a result and never as a hardware stop-complete event', () => {
  const bridge = new StartouchBridge({ simulate: false });
  const complete = [], results = [];
  bridge.on('software_stop_complete', message => complete.push(message));
  bridge.on('software_stop_result', message => results.push(message));
  bridge._handleLine(JSON.stringify({
    type: 'connection', connected: false, reason: 'software_stop',
    request_id: randomUUID(), sdk_released: true, cleanup_state: 'completed',
    stop_state: 'unknown', stop_code: 'STOP_FEEDBACK_UNAVAILABLE', source_mode: 'hardware',
  }));
  assert.equal(complete.length, 0);
  assert.equal(results.length, 1);
  assert.equal(results[0].stop_state, 'unknown');
});

test('simulation can acknowledge simulated cancellation without claiming motor depowering', () => {
  const { controller, messages, requestId } = stoppingController({ simulate: true });
  controller.bridge.emit('software_stop_result', {
    connected: false, reason: 'software_stop', request_id: requestId,
    sdk_released: true, cleanup_state: 'completed', source_mode: 'simulation',
    stop_state: 'unknown', ts: Date.now(),
  });
  const result = messages.find(message => message.type === 'command_status');
  assert.ok(result);
  assert.equal(result.stopped, true);
  assert.equal(result.sourceMode, 'simulation');
  const stop = messages.find(message => message.type === 'software_stop');
  assert.equal(stop.depowered, false);
});

test('worker exit publishes disconnection and resolves a pending stop as unknown', () => {
  const bridge = new StartouchBridge({ simulate: false, canInterface: 'test-can' });
  const messages = [], results = [], requestId = randomUUID(), child = {};
  bridge.child = child;
  bridge.connected = true;
  bridge.stopping = true;
  bridge.pendingSoftwareStopId = requestId;
  bridge.on('message', message => messages.push(message));
  bridge.on('software_stop_result', message => results.push(message));
  assert.equal(typeof bridge._handleExit, 'function');
  bridge._handleExit(child, 1, null);
  assert.equal(bridge.connected, false);
  assert.equal(bridge.pendingSoftwareStopId, null);
  assert.equal(results[0].request_id, requestId);
  assert.equal(results[0].stop_state, 'unknown');
  assert.equal(results[0].sdk_released, false);
  assert.equal(messages.at(-1).connected, false);
  assert.match(messages.at(-1).reason, /^bridge_exit:/);
});

test('a stale worker exit and mismatched stop receipt cannot settle a different outstanding stop', () => {
  const bridge = new StartouchBridge({ simulate: false });
  const child = {}, requestId = randomUUID(), results = [];
  bridge.child = child;
  bridge.connected = true;
  bridge.stopping = true;
  bridge.pendingSoftwareStopId = requestId;
  bridge.on('software_stop_result', message => results.push(message));
  assert.equal(typeof bridge._handleExit, 'function');
  bridge._handleExit({}, 1, null);
  assert.equal(bridge.child, child);
  bridge._handleLine(JSON.stringify({ type: 'connection', connected: false, reason: 'software_stop',
    request_id: randomUUID(), sdk_released: true }));
  assert.equal(results.length, 0);
  assert.equal(bridge.pendingSoftwareStopId, requestId);
});

test('in-flight private and explicit stop requests never overwrite or resend the original stop', t => {
  const bridge = new StartouchBridge({ simulate: false });
  const sent = [], results = [], first = randomUUID(), second = randomUUID();
  bridge.child = { stdin: { writable: true, write: data => sent.push(JSON.parse(data)) } };
  bridge.connected = true;
  bridge.on('software_stop_result', message => results.push(message));
  t.after(() => clearTimeout(bridge.softwareStopTimer));
  assert.equal(bridge.softwareStop(first), true);
  assert.equal(bridge.softwareStop(), true);
  assert.equal(bridge.softwareStop(second), true);
  assert.equal(sent.length, 1);
  assert.equal(sent[0].request_id, first);
  assert.equal(bridge.pendingSoftwareStopId, first);
  assert.equal(results[0].request_id, second);
  assert.equal(results[0].stop_state, 'unknown');
  assert.equal(results[0].sdk_released, false);
});

function hardwareEvidence() {
  const now = 10000;
  const context = { commandId: randomUUID(), executorEpoch: randomUUID(), hardwareFingerprint: 'a'.repeat(64), now };
  const profile = { digest: 'b'.repeat(64), stop: {
    maxStopTimeMs: 1500, maxFeedbackAgeMs: 200, maxVelocityRadS: 0.01,
    maxJointDeltaDeg: 0.2, minStableDurationMs: 100, minSamples: 3,
    requiresDisabled: false, includesGripper: false,
  } };
  const evidence = { ...context, requestedAt: 9500, observedAt: 9950,
    state: 'stopped', reason: 'HARDWARE_FEEDBACK', measurement: {
      kind: 'hardware_feedback', sourceMode: 'hardware', profileDigest: profile.digest,
      jointVelocitiesRadS: [0, 0, 0, 0, 0, 0], jointDeltaDeg: [0, 0, 0, 0, 0, 0],
      sampleCount: 4, stableDurationMs: 150, driversDisabled: false,
    } };
  delete evidence.now;
  return { context, profile, evidence };
}

function validate(evidence, context, profile) {
  return require('../../../services/robot/src/stop-evidence').validateStopEvidence(evidence, context, profile);
}

test('hardware stop validation accepts a current measured stable window but keeps depowering distinct', () => {
  const { context, profile, evidence } = hardwareEvidence();
  assert.deepEqual(validate(evidence, context, profile), {
    ok: true, code: 'STOP_VERIFIED', depowered: false, coverage: { joints: 6, gripper: false },
  });
});

test('hardware stop validation rejects unknown, stale, wrong-command, wrong-executor and simulated evidence', () => {
  for (const change of [
    v => { v.evidence.state = 'unknown'; },
    v => { v.evidence.observedAt = v.context.now - 201; },
    v => { v.evidence.observedAt = v.context.now + 1; },
    v => { v.evidence.commandId = randomUUID(); },
    v => { v.evidence.executorEpoch = randomUUID(); },
    v => { v.evidence.hardwareFingerprint = 'c'.repeat(64); },
    v => { v.evidence.measurement.sourceMode = 'simulation'; },
    v => { v.evidence.measurement.kind = 'sdk_cleanup'; },
    v => { v.evidence.measurement.profileDigest = 'd'.repeat(64); },
  ]) {
    const values = hardwareEvidence(); change(values);
    assert.equal(validate(values.evidence, values.context, values.profile).ok, false);
  }
});

test('instantaneous zero velocity, excessive drift and missing driver confirmation cannot prove stop', () => {
  for (const change of [
    v => { v.evidence.measurement.sampleCount = 1; },
    v => { v.evidence.measurement.stableDurationMs = 99; },
    v => { v.evidence.measurement.jointVelocitiesRadS[3] = 0.011; },
    v => { v.evidence.measurement.jointDeltaDeg[0] = 0.201; },
    v => { v.evidence.measurement.jointVelocitiesRadS[0] = NaN; },
    v => { v.evidence.measurement.jointVelocitiesRadS = new Array(6); },
    v => { v.evidence.measurement.jointDeltaDeg = new Array(6); },
    v => { v.evidence.measurement.driversDisabled = true; v.evidence.measurement.sampleCount = 0; },
    v => { v.profile.stop.requiresDisabled = true; },
    v => { v.evidence.requestedAt = 8000; },
  ]) {
    const values = hardwareEvidence(); change(values);
    assert.equal(validate(values.evidence, values.context, values.profile).ok, false);
  }
});

test('missing trusted stop profile is closed and feedback freshness cannot exceed the 500ms bound', () => {
  const { context, profile, evidence } = hardwareEvidence();
  for (const bad of [undefined, {}, { ...profile, stop: {} }, { ...profile, stop: { ...profile.stop, maxFeedbackAgeMs: 501 } }]) {
    assert.equal(validate(evidence, context, bad).ok, false);
  }
});

test('a scope including gripper requires its own measured standstill feedback', () => {
  const { context, profile, evidence } = hardwareEvidence();
  Object.assign(profile.stop, { includesGripper: true, maxGripperVelocityMmS: 0.5, maxGripperDeltaMm: 0.2 });
  assert.equal(validate(evidence, context, profile).ok, false);
  Object.assign(evidence.measurement, { gripperVelocityMmS: 0.1, gripperDeltaMm: 0.05 });
  assert.deepEqual(validate(evidence, context, profile).coverage, { joints: 6, gripper: true });
  evidence.measurement.gripperVelocityMmS = 0.51;
  assert.equal(validate(evidence, context, profile).ok, false);
});
