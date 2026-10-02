'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { ManualJointOrchestrator, validateCandidate } = require('../../../apps/web/src/language/manual-joint-control');
const { LanguageUpstreamBridge } = require('../../../apps/web/src/language/language-upstream-bridge');
const { cameraXTarget } = require('../../../apps/web/src/language/camera-x-step');
const { RobotProxy } = require('../../../apps/web/src/robot-proxy');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const mount = { T_flange_camera: { matrix_4x4: [
  [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
] } };
const params = distanceCm => ({
  action: 'end_effector.step', axis: 'camera_x', direction: 'left', distanceCm,
});
const candidate = (distanceCm, id = 'camera-1') => ({
  candidateId: id, traceId: 'trace-1', sourceText: 'X轴向左移动1厘米',
  skill: 'manual_joint_control@1', intent: 'end_effector.step',
  createdAt: 1000, expiresAt: 120000, requiresConfirmation: true,
  payload: { params: params(distanceCm) },
});

function fixture({ probe = true, real = false, previewOk = true } = {}) {
  const state = {
    connected: true, stateFresh: true, ageMs: 10, stateName: 'IDLE',
    motionActive: false, jointsDeg: [0, 0, 0, 0, 0, 0],
    flangePositionM: [0.4, 0, 0.25], flangeEulerRad: [0, 0, 0],
  };
  const sent = [];
  const events = [];
  const orchestrator = new ManualJointOrchestrator({
    enabled: false, cameraProbeEnabled: probe, cameraRealControlEnabled: real,
    getRobotState: () => state,
    planCameraX: step => cameraXTarget(state, step, mount),
    previewPose: async () => ({
      ok: previewOk, reason: 'IK 不可达', jointsDeg: [0, 0, 0, 0, 0, 0],
    }),
    sendRobot: command => { sent.push(command); return true; },
    onMessage: (_, message) => events.push(message),
    now: () => 2000, makeRequestId: () => 'motion-1',
    schedule: () => 1, cancelSchedule: () => {},
  });
  const register = orchestrator.register.bind(orchestrator);
  orchestrator.register = (session, item) => {
    const result = register(session, item);
    if (item.intent === 'end_effector.step') {
      const plan = cameraXTarget(state, item.payload.params, mount);
      if (plan.ok) orchestrator.bindCameraPreview(session, item, {
        originPositionM: [...state.flangePositionM],
        originEulerRad: [...state.flangeEulerRad],
        targetPositionM: plan.position, targetEulerRad: plan.euler,
        timeSec: plan.timeSec, jointsDeg: [0, 0, 0, 0, 0, 0],
      });
    }
    return result;
  };
  return { state, sent, events, orchestrator };
}

test('camera X candidate requires exact action, axis, direction and <=10 cm', () => {
  assert.equal(validateCandidate(candidate(1), 2000).ok, true);
  assert.equal(validateCandidate(candidate(10.1), 2000).ok, false);
  const wrong = candidate(1);
  wrong.payload.params.axis = 'base_x';
  assert.equal(validateCandidate(wrong, 2000).ok, false);
});

test('confirmation is required and probe cannot exceed 1 cm', async () => {
  const { orchestrator, sent, events } = fixture();
  orchestrator.register('browser', candidate(2));
  assert.equal(sent.length, 0);
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  await Promise.resolve();
  assert.equal(sent.length, 0);
  assert.match(events.at(-1).message, /1 厘米以内/);
});

test('confirmed 1 cm probe sends move_l only after IK and checks measured feedback', async () => {
  const { orchestrator, state, sent, events } = fixture();
  orchestrator.register('browser', candidate(1));
  assert.equal(sent.length, 0);
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  assert.equal(sent.length, 0);
  await Promise.resolve();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].cmd, 'move_l');
  assert.ok(Math.abs(sent[0].position[0] - 0.39) < 1e-12);
  assert.deepEqual(sent[0].euler, [0, 0, 0]);
  orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: 'motion-1' });
  state.flangePositionM = [0.391, 0, 0.25];
  orchestrator.handleBridgeEvent({
    type: 'robot_state', request_id: 'motion-1', observedAtMs: 2001,
    flangePositionM: state.flangePositionM,
    flangeEulerRad: state.flangeEulerRad,
  });
  assert.equal(events.at(-1).type, 'skill.result');
  assert.equal(events.at(-1).success, true);
  assert.match(events.at(-1).message, /1.0 mm/);
});

test('failed IK never sends motion even after confirmation', async () => {
  const { orchestrator, sent, events } = fixture({ previewOk: false });
  orchestrator.register('browser', candidate(1));
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  await Promise.resolve();
  assert.equal(sent.length, 0);
  assert.equal(events.at(-1).status, 'blocked');
});

test('upstream IK preview is read only and correlated with its reply', async () => {
  const bridge = new LanguageUpstreamBridge({ endpoint: null, now: () => 2000,
    schedule: () => 1, cancelSchedule: () => {} });
  const outgoing = [];
  bridge.socket = { readyState: 1, send: raw => outgoing.push(JSON.parse(raw)) };
  bridge.connected = true;
  bridge.simulated = false;
  bridge.upstreamSpeedScale = 0.05;
  bridge.latestJointsDeg = [0, 0, 0, 0, 0, 0];
  bridge.latestFlangePositionM = [0.4, 0, 0.25];
  bridge.latestFlangeEulerRad = [0, 0, 0];
  bridge.latestRobotStateName = 'IDLE';
  bridge.latestRobotStateAtMs = 1990;
  const result = bridge.previewIk([0.39, 0, 0.25], [0, 0, 0]);
  assert.deepEqual(outgoing.map(message => message.cmd), ['preview_ik']);
  bridge._handleMessage({ type: 'ik_preview', request_id: outgoing[0].request_id,
    ok: true, joints_deg: [1, 2, 3, 4, 5, 6] });
  assert.deepEqual(await result, { ok: true, jointsDeg: [1, 2, 3, 4, 5, 6] });
  assert.deepEqual(outgoing.map(message => message.cmd), ['preview_ik']);
});

test('camera probe is blocked if flange orientation changes during IK preview', async () => {
  const { orchestrator, state, sent, events } = fixture();
  let resolvePreview;
  orchestrator.previewPose = () => new Promise(resolve => { resolvePreview = resolve; });
  orchestrator.register('browser', candidate(1));
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  state.flangeEulerRad = [0, 0, 0.05];
  resolvePreview({ ok: true });
  await Promise.resolve();
  assert.equal(sent.length, 0);
  assert.equal(events.at(-1).status, 'blocked');
});


test('camera motion can always request software stop while general Language motion is disabled', () => {
  const { orchestrator, events } = fixture();
  let stops = 0;
  orchestrator.softwareStop = () => { stops++; return true; };
  const stop = {
    candidateId: 'stop-1', traceId: 'stop-trace', sourceText: '停止',
    skill: 'manual_joint_control@1', intent: 'safety.stop.request',
    createdAt: 1000, expiresAt: 120000, requiresConfirmation: false,
    payload: { params: { action: 'safety.stop.request' } },
  };
  orchestrator.register('browser', stop);
  assert.equal(stops, 1);
  assert.equal(events.at(-1).type, 'execution.request');
});

test('approved camera motion rejects a changed origin after the visible preview', async () => {
  const { orchestrator, state, sent, events } = fixture();
  const request = candidate(1);
  orchestrator.register('browser', request);
  const plan = cameraXTarget(state, request.payload.params, mount);
  assert.equal(orchestrator.bindCameraPreview('browser', request, {
    originPositionM: [...state.flangePositionM],
    originEulerRad: [...state.flangeEulerRad],
    targetPositionM: plan.position, targetEulerRad: plan.euler,
    timeSec: plan.timeSec, jointsDeg: [0, 0, 0, 0, 0, 0],
  }), true);
  state.flangePositionM = [0.41, 0, 0.25];
  orchestrator.decide('browser', {
    candidateId: request.candidateId, traceId: request.traceId, decision: 'approve',
  });
  await Promise.resolve();
  assert.equal(sent.length, 0);
  assert.equal(events.at(-1).status, 'blocked');
});

test('camera translation fails when target position is reached but orientation drifts', async () => {
  const { orchestrator, state, events } = fixture();
  orchestrator.register('browser', candidate(1));
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  await Promise.resolve();
  orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: 'motion-1' });
  state.flangePositionM = [0.39, 0, 0.25];
  state.flangeEulerRad = [0, 0, 0.2];
  orchestrator.handleBridgeEvent({
    type: 'robot_state', observedAtMs: 2001,
    flangePositionM: state.flangePositionM,
    flangeEulerRad: state.flangeEulerRad,
  });
  assert.equal(events.at(-1).success, false);
});

test('a sub-five-millimetre request cannot succeed without actual movement', async () => {
  const { orchestrator, state, events } = fixture();
  orchestrator.register('browser', candidate(0.2));
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  await Promise.resolve();
  orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: 'motion-1' });
  orchestrator.handleBridgeEvent({
    type: 'robot_state', observedAtMs: 2001,
    flangePositionM: state.flangePositionM,
    flangeEulerRad: state.flangeEulerRad,
  });
  assert.equal(events.at(-1).success, false);
});


test('camera direction proof without nonempty mount and serial identities cannot enable real control', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-camera-proof-'));
  try {
    const mountFile = path.join(directory, 'mount.json');
    const proofFile = path.join(directory, 'proof.json');
    fs.writeFileSync(mountFile, JSON.stringify(mount));
    fs.writeFileSync(proofFile, JSON.stringify({
      leftMovesLeft: true, rightMovesRight: true,
    }));
    const proxy = new RobotProxy(null, {
      cameraMountFile: mountFile, cameraDirectionValidationFile: proofFile,
      cameraRealControlEnabled: true, cameraProbeEnabled: false,
    });
    assert.equal(proxy.cameraDirectionValidated, false);
    proxy.close();
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test('upstream completion does not clear camera motion when orientation differs from target', () => {
  const bridge = new LanguageUpstreamBridge({ endpoint: null, now: () => 2000,
    schedule: () => 1, cancelSchedule: () => {} });
  bridge.inFlight = {
    kind: 'cartesian', completeReceived: true, completedAtMs: 1990,
    targetPositionM: [0.4, 0, 0.25], targetEulerRad: [0, 0, 0],
    targetDistanceM: 0.01,
  };
  bridge.latestRobotStateAtMs = 2000;
  bridge.latestRobotStateName = 'IDLE';
  bridge.latestFlangePositionM = [0.4, 0, 0.25];
  bridge.latestFlangeEulerRad = [0, 0, 0.2];
  bridge._completeCorrelationIfVerified();
  assert.notEqual(bridge.inFlight, null);
  bridge.latestFlangeEulerRad = [0, 0, 0.01];
  bridge._completeCorrelationIfVerified();
  assert.equal(bridge.inFlight, null);
});


test('camera candidate without a successful visible IK preview cannot execute', async () => {
  const { orchestrator, sent, events } = fixture();
  orchestrator.register('browser', candidate(1));
  orchestrator.sessions.get('browser').get('camera-1').cameraPreview = null;
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  await Promise.resolve();
  assert.equal(sent.length, 0);
  assert.equal(events.at(-1).status, 'blocked');
});


test('software stop during pending camera IK prevents a later move command', async () => {
  const { orchestrator, sent } = fixture();
  let resolvePreview;
  let stops = 0;
  orchestrator.previewPose = () => new Promise(resolve => { resolvePreview = resolve; });
  orchestrator.softwareStop = () => { stops++; return true; };
  orchestrator.register('browser', candidate(1));
  orchestrator.decide('browser', {
    candidateId: 'camera-1', traceId: 'trace-1', decision: 'approve',
  });
  orchestrator.register('browser', {
    candidateId: 'stop-2', traceId: 'stop-trace', sourceText: '停止',
    skill: 'manual_joint_control@1', intent: 'safety.stop.request',
    createdAt: 1000, expiresAt: 120000, requiresConfirmation: false,
    payload: { params: { action: 'safety.stop.request' } },
  });
  resolvePreview({ ok: true, jointsDeg: [0, 0, 0, 0, 0, 0] });
  await Promise.resolve();
  assert.ok(stops >= 1);
  assert.equal(sent.length, 0);
});

test('web proxy binds successful camera IK preview to the pending candidate', async () => {
  const proxy = new RobotProxy(null, {});
  const state = {
    connected: true, stateFresh: true, ageMs: 10, stateName: 'IDLE',
    motionActive: false, flangePositionM: [0.4, 0, 0.25],
    flangeEulerRad: [0, 0, 0], jointsDeg: [0, 0, 0, 0, 0, 0],
  };
  proxy.cameraMount = mount;
  proxy.languageUpstream.getRobotState = () => state;
  proxy.languageUpstream.previewIk = async () => ({
    ok: true, jointsDeg: [1, 2, 3, 4, 5, 6],
  });
  const browser = { readyState: 1, send() {} };
  const item = candidate(1);
  item.createdAt = Date.now();
  item.expiresAt = item.createdAt + 60000;
  proxy.languageController.register(browser, item);
  await proxy._previewCameraX(browser, item);
  const bound = proxy.languageController.sessions.get(browser).get(item.candidateId).cameraPreview;
  assert.deepEqual(bound.targetPositionM, [0.39, 0, 0.25]);
  assert.deepEqual(bound.jointsDeg, [1, 2, 3, 4, 5, 6]);
  proxy.close();
});
