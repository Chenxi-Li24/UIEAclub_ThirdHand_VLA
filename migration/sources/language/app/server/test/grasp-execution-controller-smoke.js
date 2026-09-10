'use strict';

const assert = require('assert/strict');
const { GraspExecutionController } = require('../grasp-execution-controller');

const PREVIEW = `sha256:${'a'.repeat(64)}`;
const CALIBRATION = `sha256:${'b'.repeat(64)}`;
const EVIDENCE = [`sha256:${'c'.repeat(64)}`, CALIBRATION];
const REQUESTS = [
  '11111111-1111-4111-8111-111111111111',
  '22222222-2222-4222-8222-222222222222',
  '33333333-3333-4333-8333-333333333333',
  '44444444-4444-4444-8444-444444444444',
  '55555555-5555-4555-8555-555555555555',
  '66666666-6666-4666-8666-666666666666',
];

function target() {
  return {
    id: 7,
    identityId: 7,
    actionable: true,
    identityConfirmed: true,
    observedAtMs: 1_000,
    preview: {
      previewId: PREVIEW,
      identityId: 7,
      detectionId: 12,
      frame: 'robot_base',
      calibrationId: CALIBRATION,
      evidenceIds: EVIDENCE,
      pointM: [0.32, -0.11, 0.045],
      pregraspPointM: [0.32, -0.11, 0.125],
      retreatPointM: [0.32, -0.11, 0.145],
      yawRad: 0.2,
      widthM: 0.04,
      geometryAllowed: true,
      blockers: [],
      stableSamples: 5,
    },
  };
}

function setup(overrides = {}) {
  let now = 1_100;
  let requestIndex = 0;
  const commands = [];
  const audit = [];
  const controller = new GraspExecutionController({
    executionEnabled: true,
    getRobotState: () => ({
      connected: true,
      moving: false,
      stateFresh: true,
      tcpEulerRad: [3.14, 0, 0],
    }),
    getTarget: () => target(),
    sendRobot: command => { commands.push(command); return true; },
    auditLog: { append: event => audit.push(event) },
    nowMs: () => now,
    idFactory: () => REQUESTS[requestIndex++],
    ...overrides,
  });
  return { controller, commands, audit, setNow: value => { now = value; } };
}

{
  const { controller, commands } = setup();
  assert.deepEqual(
    controller.begin({ identityId: 7, previewId: PREVIEW, positionM: [9, 9, 9] }),
    { accepted: false, reason: 'browser_coordinates_forbidden' },
  );
  assert.equal(commands.length, 0);
}

{
  const { controller, commands, audit } = setup();
  const started = controller.begin({ identityId: 7, previewId: PREVIEW });
  assert.equal(started.accepted, true);
  assert.equal(started.phase, 'open');
  assert.equal(commands[0].cmd, 'gripper');
  assert.equal(commands[0].position, 1.0);
  assert.equal(commands[0].kp, 8.0);
  assert.equal(commands[0].kd, 0.1);
  assert.equal(commands[0].source, 'grasp:open');
  assert.equal(commands[0].request_id, REQUESTS[1]);

  assert.deepEqual(
    controller.onRobotEvent({
      type: 'command_complete', command: 'gripper', request_id: REQUESTS[4],
    }),
    { handled: false, reason: 'request_mismatch' },
  );
  assert.equal(commands.length, 1);

  assert.equal(controller.onRobotEvent({
    type: 'command_complete', command: 'gripper', request_id: REQUESTS[1], reached: true,
  }).handled, true);
  assert.equal(commands[1].source, 'grasp:pregrasp');
  assert.deepEqual(commands[1].position, [0.32, -0.11, 0.125]);

  assert.equal(controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[2], reached: true,
  }).handled, true);
  assert.equal(commands[2].source, 'grasp:descend');
  assert.deepEqual(commands[2].position, [0.32, -0.11, 0.045]);

  assert.equal(controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[3], reached: true,
  }).handled, true);
  assert.equal(commands[3].cmd, 'gripper');
  assert.equal(commands[3].position, 0.0);
  assert.equal(commands[3].kp, 2.0);
  assert.equal(commands[3].kd, 0.1);
  assert.equal(commands[3].source, 'grasp:close');
  assert.equal(commands[3].request_id, REQUESTS[4]);

  const contact = controller.onRobotEvent({
    type: 'command_complete', command: 'gripper', request_id: REQUESTS[4],
    reached: false, moved: true, actual_position: 0.25,
  });
  assert.equal(contact.handled, true);
  assert.equal(commands[4].source, 'grasp:retreat');

  const complete = controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[5], reached: true,
  });
  assert.equal(complete.status, 'complete');
  assert.equal(controller.active, false);
  assert.equal(audit.some(event => event.action === 'grasp_complete'), true);
}

{
  const { controller, commands } = setup();
  controller.begin({ identityId: 7, previewId: PREVIEW });
  controller.onRobotEvent({
    type: 'command_complete', command: 'gripper', request_id: REQUESTS[1], reached: true,
  });
  controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[2], reached: true,
  });
  controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[3], reached: true,
  });
  const empty = controller.onRobotEvent({
    type: 'command_complete', command: 'gripper', request_id: REQUESTS[4],
    reached: true, moved: true, actual_position: 0.0,
  });
  assert.equal(empty.status, 'recovery_retreat');
  assert.equal(empty.reason, 'object_contact_not_detected');
  assert.equal(controller.active, true);
  assert.equal(commands[4].source, 'grasp:recovery_retreat');
  const recovered = controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[5], reached: true,
  });
  assert.equal(recovered.reason, 'object_contact_not_detected');
  assert.equal(controller.active, false);
  assert.equal(commands.length, 5);
}

{
  const { controller, commands } = setup();
  controller.begin({ identityId: 7, previewId: PREVIEW });
  const failed = controller.onRobotEvent({
    type: 'command_complete', command: 'move_l', request_id: REQUESTS[1], reached: true,
  });
  assert.deepEqual(failed, { handled: false, reason: 'command_mismatch' });
  assert.equal(commands.length, 1);
  assert.equal(controller.active, true);
}

for (const event of [
  { type: 'connection', connected: false },
  { type: 'software_stop' },
  { type: 'vision_invalidated', reason: 'evidence_changed' },
]) {
  const { controller } = setup();
  controller.begin({ identityId: 7, previewId: PREVIEW });
  assert.equal(controller.onRobotEvent(event).handled, true, event.type);
  assert.equal(controller.active, false, event.type);
}

{
  const { controller, setNow } = setup();
  controller.begin({ identityId: 7, previewId: PREVIEW });
  setNow(31_101);
  assert.equal(controller.checkTimeout().reason, 'step_timeout');
  assert.equal(controller.active, false);
}

{
  const changed = target();
  changed.preview.previewId = `sha256:${'d'.repeat(64)}`;
  const { controller, commands } = setup({ getTarget: () => changed });
  assert.deepEqual(
    controller.begin({ identityId: 7, previewId: PREVIEW }),
    { accepted: false, reason: 'preview_mismatch' },
  );
  assert.equal(commands.length, 0);
}

console.log('PASS grasp controller freezes server preview and correlates every step');
