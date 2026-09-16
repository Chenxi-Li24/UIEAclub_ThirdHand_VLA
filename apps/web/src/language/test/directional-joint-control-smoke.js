'use strict';

const assert = require('assert/strict');
const {
  DIRECTIONAL_SKILL,
  DIRECTIONAL_ACTIONS,
  DirectionalJointOrchestrator,
  computeDirectionalTarget,
  normalizeDirectionalMoves,
  validateDirectionalCandidate,
} = require('../directional-joint-control');

const NOW = 10_000;
const LIMITS = [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]];
const CURRENT = [10, 20, -30, 5, 6, 7];

function candidate(action, overrides = {}) {
  const deltaDeg = overrides.deltaDeg ?? 20;
  return {
    candidateId: overrides.candidateId || `candidate-${action}`,
    traceId: overrides.traceId || `trace-${action}`,
    sourceText: overrides.sourceText || action,
    skill: DIRECTIONAL_SKILL,
    createdAt: overrides.createdAt ?? NOW,
    expiresAt: overrides.expiresAt ?? NOW + 120_000,
    requiresConfirmation: overrides.requiresConfirmation ?? true,
    intent: overrides.intent || action,
    payload: { params: { action, deltaDeg, ...(overrides.extraParams || {}) } },
  };
}

function compoundCandidate(moves, overrides = {}) {
  return {
    candidateId: overrides.candidateId || 'candidate-compound',
    traceId: overrides.traceId || 'trace-compound',
    sourceText: overrides.sourceText || '抬高点，向左点',
    skill: DIRECTIONAL_SKILL,
    createdAt: overrides.createdAt ?? NOW,
    expiresAt: overrides.expiresAt ?? NOW + 120_000,
    requiresConfirmation: overrides.requiresConfirmation ?? true,
    intent: overrides.intent || 'directional.compound',
    payload: { params: { moves, ...(overrides.extraParams || {}) } },
  };
}

function harness(overrides = {}) {
  let state = {
    simulated: false,
    connected: true,
    stateFresh: true,
    ageMs: 10,
    stateName: 'IDLE',
    motionActive: false,
    jointsDeg: [...CURRENT],
  };
  const commands = [];
  const messages = [];
  const stops = [];
  const timers = [];
  const orchestrator = new DirectionalJointOrchestrator({
    enabled: true,
    realControlEnabled: true,
    getRobotState: () => ({ ...state, jointsDeg: [...state.jointsDeg] }),
    sendRobot: command => { commands.push(command); return true; },
    softwareStop: () => { stops.push(true); return true; },
    moveTimeFor: () => 1,
    jointLimitsDeg: LIMITS,
    now: () => NOW,
    makeRequestId: () => 'directional-request-1',
    schedule: callback => { timers.push(callback); return callback; },
    cancelSchedule: () => {},
    onMessage: (session, message) => messages.push({ session, message }),
    ...overrides,
  });
  return {
    orchestrator, commands, messages, stops, timers,
    setState(next) { state = { ...state, ...next }; },
  };
}

function last(h) {
  return h.messages.at(-1)?.message;
}

const mappings = new Map([
  ['turn.left', [30, 20, -30, 5, 6, 7]],
  ['turn.right', [-10, 20, -30, 5, 6, 7]],
  ['lift.up', [10, 40, -50, 5, 6, 7]],
  ['lift.down', [10, 0, -10, 5, 6, 7]],
  ['wrist.pitch.up', [10, 20, -30, -15, 6, 7]],
  ['wrist.pitch.down', [10, 20, -30, 25, 6, 7]],
  ['wrist.yaw.left', [10, 20, -30, 5, 26, 7]],
  ['wrist.yaw.right', [10, 20, -30, 5, -14, 7]],
  ['wrist.roll.clockwise', [10, 20, -30, 5, 6, 27]],
  ['wrist.roll.counterclockwise', [10, 20, -30, 5, 6, -13]],
]);
assert.deepEqual([...DIRECTIONAL_ACTIONS], [...mappings.keys()]);
for (const [action, expected] of mappings) {
  const result = computeDirectionalTarget({
    currentJointsDeg: CURRENT,
    action,
    deltaDeg: 20,
    jointLimitsDeg: LIMITS,
  });
  assert.equal(result.ok, true, `${action}: ${result.reason}`);
  assert.deepEqual(result.targetJointsDeg, expected);
}

{
  assert.deepEqual(normalizeDirectionalMoves({ action: 'turn.left', deltaDeg: 20 }), {
    ok: true,
    moves: [{ action: 'turn.left', deltaDeg: 20 }],
    compound: false,
  });
  assert.deepEqual(normalizeDirectionalMoves({ moves: [
    { action: 'lift.up', deltaDeg: 20 },
    { action: 'turn.left', deltaDeg: 20 },
  ] }), {
    ok: true,
    moves: [
      { action: 'lift.up', deltaDeg: 20 },
      { action: 'turn.left', deltaDeg: 20 },
    ],
    compound: true,
  });
  assert.equal(normalizeDirectionalMoves({ moves: [
    { action: 'turn.left', deltaDeg: 20 },
    { action: 'turn.right', deltaDeg: 20 },
  ] }).ok, false);
}

{
  const c = compoundCandidate([
    { action: 'lift.up', deltaDeg: 20 },
    { action: 'turn.left', deltaDeg: 20 },
  ]);
  const checked = validateDirectionalCandidate(c, NOW);
  assert.equal(checked.ok, true, checked.reason);
  assert.deepEqual(checked.params, { moves: [
    { action: 'lift.up', deltaDeg: 20 },
    { action: 'turn.left', deltaDeg: 20 },
  ] });
}

{
  const result = computeDirectionalTarget({
    currentJointsDeg: CURRENT,
    moves: [
      { action: 'lift.up', deltaDeg: 20 },
      { action: 'turn.left', deltaDeg: 20 },
    ],
    jointLimitsDeg: LIMITS,
    // Large J1 motion would dominate XY if lift validation incorrectly used the combined target.
    forwardKinematics: joints => [joints[0] * 3, 0, joints[1] - joints[2]],
  });
  assert.equal(result.ok, true, result.reason);
  assert.deepEqual(result.targetJointsDeg, [30, 40, -50, 5, 6, 7]);
  assert.deepEqual(result.changedJointIndices, [0, 1, 2]);
}

{
  const result = computeDirectionalTarget({
    currentJointsDeg: CURRENT,
    action: 'turn.left',
    deltaDeg: 35,
    jointLimitsDeg: LIMITS,
  });
  assert.deepEqual(result.targetJointsDeg, [45, 20, -30, 5, 6, 7]);
}

{
  const result = computeDirectionalTarget({
    currentJointsDeg: [160, 20, -30, 5, 6, 7],
    action: 'turn.left',
    deltaDeg: 20,
    jointLimitsDeg: LIMITS,
  });
  assert.equal(result.ok, false);
  assert.match(result.reason, /J1.*限位/);
}

{
  const result = computeDirectionalTarget({
    currentJointsDeg: [170, -20, -100, 0, 0, 0],
    action: 'turn.left',
    deltaDeg: 20,
    jointLimitsDeg: LIMITS,
  });
  assert.equal(result.ok, false);
  assert.match(result.reason, /J1.*162/);
  assert.match(result.reason, /J2.*-12/);
}

{
  const result = computeDirectionalTarget({
    currentJointsDeg: [0, 100, -100, 0, 0, 0],
    action: 'lift.up',
    deltaDeg: 20,
    jointLimitsDeg: LIMITS,
  });
  assert.equal(result.ok, false);
  assert.match(result.reason, /抬高.*方向校验/);
}

{
  const c = candidate('turn.left', { extraParams: { speedScale: 1 } });
  assert.equal(validateDirectionalCandidate(c, NOW).ok, false);
}

{
  const h = harness();
  const c = candidate('lift.up');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 1);
  assert.equal(h.commands[0].cmd, 'move_joint');
  assert.equal(h.commands[0].speed_scale, 0.05);
  assert.deepEqual(
    h.commands[0].joints_rad.map(value => Math.round(value * 180 / Math.PI)),
    [10, 40, -50, 5, 6, 7]
  );
  assert.deepEqual(h.commands[0].directional_authorization, {
    skill: DIRECTIONAL_SKILL,
    action: 'lift.up',
    deltaDeg: 20,
  });
  assert.equal(h.messages.some(item => item.message.type === 'execution.request'), true);

  h.orchestrator.handleBridgeEvent({ type: 'command_complete', request_id: 'directional-request-1' });
  h.orchestrator.handleBridgeEvent({
    type: 'robot_state', observedAtMs: NOW, stateName: 'IDLE',
    joints: [10, 40, -50, 5, 6, 7],
  });
  assert.equal(last(h).type, 'skill.result');
  assert.equal(last(h).success, true);
}

{
  const h = harness({
    forwardKinematics: joints => [joints[0] * 3, 0, joints[1] - joints[2]],
  });
  const c = compoundCandidate([
    { action: 'lift.up', deltaDeg: 20 },
    { action: 'turn.left', deltaDeg: 20 },
  ]);
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 1);
  assert.deepEqual(
    h.commands[0].joints_rad.map(value => Math.round(value * 180 / Math.PI)),
    [30, 40, -50, 5, 6, 7]
  );
  assert.deepEqual(h.commands[0].directional_authorization, {
    skill: DIRECTIONAL_SKILL,
    moves: [
      { action: 'lift.up', deltaDeg: 20 },
      { action: 'turn.left', deltaDeg: 20 },
    ],
  });
}

{
  const h = harness({ realControlEnabled: false });
  const c = candidate('turn.left');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
  assert.match(last(h).message, /DIRECTIONAL_REAL_CONTROL/);
}

for (const badState of [
  { connected: false },
  { stateFresh: false, ageMs: 501 },
  { stateName: 'MOVING' },
  { motionActive: true },
]) {
  const h = harness();
  h.setState(badState);
  const c = candidate('turn.left');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.equal(last(h).status, 'blocked');
}

{
  const h = harness();
  const c = candidate('turn.left');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: 'wrong-trace', decision: 'approve',
  });
  assert.equal(h.commands.length, 0);
  assert.match(last(h).message, /trace/);
}

{
  const h = harness();
  const c = candidate('turn.left');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  h.timers[0]();
  assert.equal(h.stops.length, 1);
  assert.equal(last(h).success, false);
  assert.match(last(h).message, /超时/);
}

{
  const h = harness();
  const c = candidate('turn.left');
  h.orchestrator.register('browser-a', c);
  h.orchestrator.decide('browser-a', {
    candidateId: c.candidateId, traceId: c.traceId, decision: 'approve',
  });
  h.orchestrator.disconnect('browser-a');
  assert.equal(h.stops.length, 1);
  assert.equal(last(h).success, false);
  assert.match(last(h).message, /页面断开/);
}

console.log('PASS directional joint control is deterministic and confirmation-gated');
