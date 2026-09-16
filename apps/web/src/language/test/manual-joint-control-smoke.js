'use strict';

const assert = require('assert');
const { ManualJointOrchestrator, validateCandidate } = require('../manual-joint-control');
const { PICK_SKILL, SkillExecutorRegistry } = require('../skill-executor-registry');

const NOW = 1_700_000_000_000;

function candidate(action, extra = {}) {
  return {
    candidateId: extra.candidateId || `candidate-${action}`,
    traceId: extra.traceId || `trace-${action}`,
    sourceText: extra.sourceText || action,
    skill: extra.skill || 'manual_joint_control@1',
    intent: action,
    createdAt: NOW,
    expiresAt: extra.expiresAt ?? NOW + 120_000,
    requiresConfirmation: extra.requiresConfirmation ?? action !== 'safety.stop.request',
    payload: { params: { action, ...(extra.params || {}) } },
  };
}

function pickCandidate() {
  return {
    candidateId: 'candidate-pick-coke',
    traceId: 'trace-pick-coke',
    sourceText: '拿一个可乐放到 B 区',
    skill: PICK_SKILL,
    createdAt: NOW,
    expiresAt: NOW + 120_000,
    requiresConfirmation: true,
    payload: {
      params: {
        object: 'coke_bottle',
        destination: { id: 'drop_zone_b', type: 'configured_drop_zone' },
      },
    },
  };
}

function harness(overrides = {}) {
  const messages = [];
  const commands = [];
  const stops = [];
  const timers = [];
  let state = {
    connected: true,
    stateFresh: true,
    ageMs: 20,
    stateName: 'IDLE',
    motionActive: false,
    activeViewActive: false,
    graspActive: false,
    jointsDeg: [0, 0, -10, 0, 0, 0],
    simulated: true,
  };
  const orchestrator = new ManualJointOrchestrator({
    enabled: true,
    now: () => NOW,
    makeRequestId: () => `request-${commands.length + 1}`,
    getRobotState: () => state,
    sendRobot: command => { commands.push(command); return true; },
    softwareStop: () => { stops.push(true); return true; },
    moveTimeFor: () => 0.5,
    getHomeTarget: () => [0, 0, 0, 0, 0, 0],
    onMessage: (session, message) => messages.push({ session, message }),
    schedule: callback => { timers.push(callback); return callback; },
    cancelSchedule: () => {},
    jointLimitsDeg: [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
    ...overrides,
  });
  return {
    orchestrator, messages, commands, stops, timers,
    setState: next => { state = { ...state, ...next }; },
  };
}

function last(h) {
  return h.messages.at(-1)?.message;
}

{
  const invalid = candidate('joint.step', { params: { joint: 1, deltaDeg: 1 }, expiresAt: NOW - 1 });
  assert.equal(validateCandidate(invalid, NOW).ok, false);
  assert.match(validateCandidate(invalid, NOW).reason, /过期/);
}

{
  const h = harness();
  const c = candidate('joint.step', { params: { joint: 1, deltaDeg: 1 } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: 'wrong', decision: 'approve' });
  assert.equal(h.commands.length, 0);
  assert.match(last(h).message, /trace/);
}

{
  const h = harness();
  assert.equal(h.orchestrator.runtimeConfig().maxDeltaDeg, null);
  const c = candidate('joint.step', { params: { joint: 1, deltaDeg: 20 } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 1);
  assert.equal(h.commands[0].cmd, 'move_joint');
  assert(Math.abs(h.commands[0].joints_rad[0] - 20 * Math.PI / 180) < 1e-9);

  const overlapping = candidate('joint.step', {
    candidateId: 'candidate-overlapping', traceId: 'trace-overlapping',
    params: { joint: 2, deltaDeg: 1 },
  });
  h.orchestrator.register('browser-a', overlapping);
  h.orchestrator.decide('browser-a', {
    candidateId: overlapping.candidateId, traceId: overlapping.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 1);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /Language 动作正在执行/);
}

{
  const h = harness();
  const c = candidate('joint.multi', { params: { moves: [
    { joint: 1, deltaDeg: 10 }, { joint: 2, deltaDeg: -10 }, { joint: 3, targetDeg: -20 },
  ] } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 1);
  assert.equal(h.commands[0].cmd, 'move_joint');
  assert.equal(h.commands[0].speed_scale, 0.05);
  assert.deepStrictEqual(h.commands[0].manual_joint_authorization.moves, c.payload.params.moves);
  const degrees = h.commands[0].joints_rad.map(value => value * 180 / Math.PI);
  assert(degrees.every((value, index) => Math.abs(value - [10, -10, -20, 0, 0, 0][index]) < 1e-9));
  h.orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: 'wrong-request' });
  assert.notEqual(last(h).type, 'skill.result');
  h.orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: h.commands[0].request_id });
  h.orchestrator.handleBridgeEvent({ type: 'robot_state', ts: NOW, joints: [10, -10, -20, 0, 0, 0] });
  assert.equal(last(h).type, 'skill.result');
  assert.equal(last(h).success, true);
}

{
  const h = harness();
  const c = candidate('joint.multi', { params: { moves: [
    { joint: 1, targetDeg: 163 }, { joint: 2, targetDeg: -13 },
  ] } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /J1.*162/);
  assert.match(last(h).message, /J2.*-12/);
}

{
  const c = candidate('joint.multi', { params: { moves: [
    { joint: 1, deltaDeg: 10 }, { joint: 1, deltaDeg: -10 },
  ] } });
  assert.equal(validateCandidate(c, NOW).ok, false);
}

{
  const h = harness();
  const c = candidate('joint.set', { params: { joint: 1, targetDeg: 163 } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /关节限位/);
}

{
  const h = harness();
  const c = candidate('joint.step', { params: { joint: 1, deltaDeg: 1 } });
  h.setState({ ageMs: 501, stateFresh: false });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 0);
  assert.match(last(h).message, /500ms/);
}

{
  const h = harness();
  const c = candidate('joint.step', { params: { joint: 1, deltaDeg: 1 } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 1);
  assert.equal(h.commands[0].cmd, 'move_joint');
  assert.equal(h.commands[0].speed_scale, 0.05);
  h.orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: h.commands[0].request_id });
  h.orchestrator.handleBridgeEvent({ type: 'robot_state', ts: NOW, joints: [1, 0, -10, 0, 0, 0] });
  assert.equal(last(h).type, 'skill.result');
  assert.equal(last(h).success, true);
  assert.equal(last(h).simulated, true);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 1);
  assert.match(last(h).message, /已经消费/);
}

{
  const h = harness();
  const c = candidate('gripper.open');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands[0].cmd, 'gripper');
  assert.equal(h.commands[0].position, 1);
  h.orchestrator.handleBridgeEvent({
    type: 'command_complete', request_id: h.commands[0].request_id, reached: true,
  });
  assert.equal(last(h).success, true);
}

{
  const h = harness();
  h.setState({ jointsDeg: [10, 20, -30, 5, 6, 7] });
  const c = candidate('robot.home');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 1);
  assert.equal(h.commands[0].cmd, 'preset_home');
  assert.equal(h.commands[0].name, 'home');
  h.orchestrator.handleBridgeEvent({
    type: 'command_complete', request_id: h.commands[0].request_id,
  });
  h.orchestrator.handleBridgeEvent({
    type: 'robot_state', ts: NOW, joints: [0, 0, 0, 0, 0, 0],
  });
  assert.equal(last(h).type, 'skill.result');
  assert.equal(last(h).success, true);
  assert.match(last(h).message, /Home/);
}

{
  const h = harness({ getHomeTarget: () => [163, 0, 0, 0, 0, 0] });
  const c = candidate('robot.home');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /J1.*163.*-162.*162/);
}

{
  const h = harness();
  const c = candidate('safety.stop.request');
  h.orchestrator.register('browser-a', c);
  assert.equal(h.stops.length, 1);
  assert.equal(h.commands.length, 0);
  h.orchestrator.handleBridgeEvent({ type: 'software_stop_complete' });
  assert.equal(last(h).success, true);
}

{
  const h = harness({ enabled: false });
  const c = candidate('joint.set', { params: { joint: 1, targetDeg: 1 } });
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', { candidateId: c.candidateId, traceId: c.traceId, decision: 'approve' });
  assert.equal(h.commands.length, 0);
  assert.match(last(h).message, /LANGUAGE_REAL_CONTROL/);
}

{
  const h = harness({ enabled: false });
  const c = candidate('safety.stop.request');
  h.orchestrator.register('browser-a', c);
  assert.equal(h.stops.length, 0);
  assert.match(last(h).message, /LANGUAGE_REAL_CONTROL/);
}

{
  const h = harness({ skillExecutors: new SkillExecutorRegistry() });
  const c = pickCandidate();
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /尚未注册/);
}

{
  const registry = new SkillExecutorRegistry();
  let handoff = null;
  registry.register(PICK_SKILL, {
    start(request) { handoff = request; return { status: 'pending' }; },
  });
  const h = harness({ skillExecutors: registry });
  const c = pickCandidate();
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.equal(handoff.skill, PICK_SKILL);
  assert.equal(handoff.confirmation.decision, 'confirmed');
  assert.equal(last(h).type, 'skill.handoff.accepted');
}

console.log('manual-joint-control smoke: PASS');
