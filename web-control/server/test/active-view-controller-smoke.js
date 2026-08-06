'use strict';

const assert = require('assert/strict');
const { ActiveViewController } = require('../active-view-controller');
const { approvalContentId } = require('../active-view-authorization');

const EVIDENCE = `sha256:${'a'.repeat(64)}`;
const SESSION_ID = '11111111-1111-4111-8111-111111111111';
const PROPOSAL_ID = '22222222-2222-4222-8222-222222222222';
const REQUEST_ID = '33333333-3333-4333-8333-333333333333';
const limits = {
  maxSpeedScale: 0.05,
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
  maxRefinementSteps: 3,
  requireStepConfirmation: true,
  robotModelId: 'startouch-fasttouch-v3',
  jointLimitsDeg: [
    [-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164],
  ],
};
const approvalPayload = {
  schema_version: 1,
  issued_at_ms: 500,
  expires_at_ms: 2_000,
  operator_acknowledged: true,
  robot_model_id: limits.robotModelId,
  evidence_ids: [EVIDENCE],
  limits: {
    max_speed_scale: 0.05,
    max_translation_m: 0.020,
    max_rotation_rad: limits.maxRotationRad,
    max_refinement_steps: 3,
    require_step_confirmation: true,
  },
};
const approval = { ...approvalPayload, content_id: approvalContentId(approvalPayload) };

function proposal() {
  return {
    type: 'active_view_move_proposal',
    session_id: SESSION_ID,
    proposal_id: PROPOSAL_ID,
    identity_id: 9,
    kind: 'coarse_pose',
    source_frame_id: 7,
    source_monotonic_ns: '1000000000',
    expires_ns: '1200000000',
    target_pose_id: 'table_center',
    joints_deg: [1, 20, -40, 0, 10, 0],
    delta_base_m: null,
    optical_axis_base: null,
    rotation_delta_rad: null,
    evidence_ids: [EVIDENCE],
    active_view_execution_enabled: false,
    robot_execution_enabled: false,
  };
}

function setup({ sendRobot = command => true } = {}) {
  let now = 1_000;
  const robotCommands = [];
  const visionCommands = [];
  const auditEvents = [];
  const controller = new ActiveViewController({
    requested: true,
    loadApproval: () => approval,
    limits,
    nowMs: () => now,
    idFactory: () => REQUEST_ID,
    sendRobot: command => { robotCommands.push(command); return sendRobot(command); },
    sendVision: command => { visionCommands.push(command); return true; },
    auditLog: { append: event => auditEvents.push(event) },
    getRobotState: () => ({
      connected: true,
      moving: false,
      stateFresh: true,
      graspActive: false,
      currentJointsDeg: [1, 15, -35, 0, 8, 0],
    }),
  });
  return {
    controller, robotCommands, visionCommands, auditEvents,
    setNow: value => { now = value; },
  };
}

{
  const { controller, visionCommands } = setup({ sendRobot: () => false });
  controller.begin({ sessionId: SESSION_ID, identityId: 9 });
  controller.onVisionEvent(proposal());
  assert.deepEqual(
    controller.confirm({ sessionId: SESSION_ID, proposalId: PROPOSAL_ID }),
    { approved: false, reason: 'robot_transport_unavailable' }
  );
  assert.equal(controller.pending, null);
  assert.equal(controller.inFlight, null);
  assert.equal(controller.session, null);
  assert.equal(visionCommands.at(-1).type, 'active_view_motion_failed');
}

{
  const { controller, robotCommands, visionCommands, auditEvents } = setup();
  assert.deepEqual(
    controller.begin({ sessionId: SESSION_ID, identityId: 9 }),
    { accepted: true, sessionId: SESSION_ID }
  );
  assert.deepEqual(visionCommands[0], {
    type: 'active_view_start', session_id: SESSION_ID, identity_id: 9,
  });
  assert.equal(controller.onVisionEvent(proposal()).accepted, true);

  const injection = controller.confirm({
    sessionId: SESSION_ID,
    proposalId: PROPOSAL_ID,
    jointsDeg: [0, 0, 0, 0, 0, 0],
  });
  assert.deepEqual(injection, { approved: false, reason: 'browser_coordinates_forbidden' });
  assert.equal(robotCommands.length, 0);

  const confirmed = controller.confirm({ sessionId: SESSION_ID, proposalId: PROPOSAL_ID });
  assert.equal(confirmed.approved, true);
  assert.equal(confirmed.requestId, REQUEST_ID);
  assert.deepEqual(robotCommands[0].joints_rad, proposal().joints_deg.map(value => value * Math.PI / 180));
  assert.equal(robotCommands[0].request_id, REQUEST_ID);
  assert.equal(controller.pending, null);
  assert.equal(controller.inFlight.requestId, REQUEST_ID);
  assert.equal(auditEvents.some(event => event.action === 'motion_authorized'), true);

  assert.deepEqual(
    controller.onRobotEvent({ type: 'command_complete', request_id: '44444444-4444-4444-8444-444444444444' }),
    { handled: false, reason: 'request_mismatch' }
  );
  assert.notEqual(controller.inFlight, null);
  assert.equal(controller.onRobotEvent({ type: 'command_complete', request_id: REQUEST_ID }).handled, true);
  assert.equal(controller.inFlight, null);
  assert.equal(visionCommands.at(-1).type, 'active_view_motion_completed');
}

{
  const { controller, robotCommands } = setup();
  controller.begin({ sessionId: SESSION_ID, identityId: 9 });
  controller.onVisionEvent(proposal());
  assert.deepEqual(
    controller.confirm({
      sessionId: SESSION_ID,
      proposalId: '55555555-5555-4555-8555-555555555555',
    }),
    { approved: false, reason: 'proposal_not_pending' }
  );
  assert.equal(robotCommands.length, 0);
}

for (const event of [
  { type: 'connection', connected: false },
  { type: 'software_stop' },
  { type: 'grasp_started' },
  { type: 'active_view_evidence_changed', evidence_ids: [`sha256:${'b'.repeat(64)}`] },
]) {
  const { controller, visionCommands } = setup();
  controller.begin({ sessionId: SESSION_ID, identityId: 9 });
  controller.onVisionEvent(proposal());
  controller.confirm({ sessionId: SESSION_ID, proposalId: PROPOSAL_ID });
  const result = event.type === 'active_view_evidence_changed'
    ? controller.onVisionEvent(event)
    : controller.onRobotEvent(event);
  assert.equal(result.handled, true, event.type);
  assert.equal(controller.pending, null, event.type);
  assert.equal(controller.inFlight, null, event.type);
  assert.equal(visionCommands.at(-1).type, 'active_view_motion_failed', event.type);
}

{
  const { controller, setNow, visionCommands } = setup();
  controller.begin({ sessionId: SESSION_ID, identityId: 9 });
  controller.onVisionEvent(proposal());
  controller.confirm({ sessionId: SESSION_ID, proposalId: PROPOSAL_ID });
  setNow(1_000 + controller.motionTimeoutMs + 1);
  assert.equal(controller.checkTimeout().handled, true);
  assert.equal(controller.inFlight, null);
  assert.equal(visionCommands.at(-1).reason, 'motion_timeout');
}

{
  const { controller, robotCommands } = setup();
  controller.begin({ sessionId: SESSION_ID, identityId: 9 });
  controller.onVisionEvent(proposal());
  controller.auditLog.append = () => { throw new Error('disk full'); };
  assert.deepEqual(
    controller.confirm({ sessionId: SESSION_ID, proposalId: PROPOSAL_ID }),
    { approved: false, reason: 'audit_write_failed' }
  );
  assert.equal(robotCommands.length, 0);
}

console.log('PASS active-view controller owns proposals and correlates motion');
