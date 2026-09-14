'use strict';

const assert = require('assert/strict');
const { GraspController } = require('../grasp-controller');
const { authorizeGraspPlan } = require('../grasp-authorization');

function target(overrides = {}) {
  return {
    id: 7,
    identityId: 'bottle-L1',
    calibrationId: 'cal-2026-08-17',
    observedAtMs: 1000,
    previewId: 'a'.repeat(64),
    graspM: [0.30, 0.02, 0.12],
    pregraspM: [0.30, 0.02, 0.20],
    retreatM: [0.30, 0.02, 0.24],
    widthM: 0.04,
    yawRad: 0,
    actionable: true,
    calibrationValidated: true,
    depthValid: true,
    identityConfirmed: true,
    armStationary: true,
    safetyApproved: true,
    previewAllowed: true,
    ...overrides,
  };
}

function harness(mode) {
  const sent = [];
  let latest = target();
  let nowMs = 1100;
  const controller = new GraspController({
    sendRobot(command) {
      sent.push(command);
      return true;
    },
    authorizePlan(candidate, expectations = {}) {
      return authorizeGraspPlan({
        executionEnabled: true,
        bridgeConnected: true,
        armMotionActive: false,
        robotStateFresh: true,
        target: candidate,
        nowMs,
        ...expectations,
      });
    },
    canContinue: () => ({ approved: true }),
  });
  controller.updateTarget(latest);
  assert.equal(controller.start(mode).ok, true);
  return {
    controller,
    sent,
    update(overrides) {
      latest = target(overrides);
      controller.updateTarget(latest);
    },
    setNow(value) {
      nowMs = value;
    },
  };
}

{
  const { controller, sent, update } = harness('step');
  assert.equal(sent[0].cmd, 'move_l');
  assert.deepEqual(sent[0].position_m, [0.30, 0.02, 0.20]);

  const hoverRequestId = sent[0].request_id;
  assert.equal(controller.complete('move_l', 'late-request'), false);
  assert.equal(controller.snapshot().phase, 'hover');
  controller.complete('move_l', hoverRequestId);
  assert.equal(controller.snapshot().phase, 'preview_ready');
  update({ observedAtMs: 1100, previewId: 'b'.repeat(64) });
  assert.equal(controller.advance().ok, true);
  assert.deepEqual(sent[1].position_m, [0.30, 0.02, 0.12]);

  controller.complete('move_l', sent[1].request_id);
  assert.equal(controller.advance().ok, true);
  assert.equal(sent[2].cmd, 'gripper');
  assert.equal(sent[2].position, 0.5);

  controller.complete('gripper');
  assert.equal(controller.advance().ok, true);
  assert.deepEqual(sent[3].position_m, [0.30, 0.02, 0.24]);
  controller.complete('move_l', sent[3].request_id);
  assert.equal(controller.snapshot().phase, 'holding');
  assert.equal(sent.length, 4);
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  assert.equal(controller.snapshot().phase, 'awaiting_fresh_preview');
  assert.equal(sent.length, 1);

  update({ observedAtMs: 1100, previewId: 'b'.repeat(64) });
  assert.equal(sent.length, 2);
  assert.deepEqual(sent[1].position_m, [0.30, 0.02, 0.12]);
  controller.complete('move_l', sent[1].request_id);
  controller.complete('gripper');
  controller.complete('move_l', sent[3].request_id);
  assert.equal(controller.snapshot().phase, 'holding');
  assert.equal(sent.length, 4);
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({
    observedAtMs: 1100,
    previewId: 'c'.repeat(64),
    graspM: [0.40, 0.02, 0.12],
  });
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_position_shifted');
  assert.equal(sent.length, 1);
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: 'f'.repeat(64) });
  assert.equal(sent[1].cmd, 'move_l');

  controller.updateTarget(null);
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_lost');

  update({ observedAtMs: 1110, previewId: '6'.repeat(64) });
  assert.equal(controller.snapshot().phase, 'aborted', 'a recovered target must not resume the task');
  assert.equal(controller.complete('move_l', sent[1].request_id), false);
  assert.equal(sent.length, 2, 'target loss during descend must not close the gripper');
}

{
  const { controller, sent, update } = harness('auto');
  update({ graspM: [Number.NaN, 0.02, 0.12] });

  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_position_invalid');
  assert.equal(sent.length, 1, 'invalid pose during hover must latch the task aborted');
}

{
  const { controller, sent, update } = harness('step');
  controller.complete('move_l', sent[0].request_id);
  assert.equal(controller.snapshot().phase, 'preview_ready');

  update({ calibrationId: 'cal-replaced' });

  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'calibration_changed');
  assert.equal(sent.length, 1);
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: '1'.repeat(64) });

  update({
    observedAtMs: 1100,
    previewId: '2'.repeat(64),
    graspM: [Number.NaN, 0.02, 0.12],
  });
  controller.complete('move_l', sent[1].request_id);

  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_position_invalid');
  assert.equal(sent.length, 2, 'invalid pose before close must not close the gripper');
}

{
  const { controller, sent, update, setNow } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: '3'.repeat(64) });

  setNow(1400);
  controller.complete('move_l', sent[1].request_id);

  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_stale');
  assert.equal(sent.length, 2, 'stale target before close must not close the gripper');
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: '5'.repeat(64) });
  controller.complete('move_l', sent[1].request_id);
  assert.equal(sent[2].cmd, 'gripper');

  update({ identityId: 'bottle-R3' });
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_identity_changed');
  assert.equal(controller.complete('gripper'), false);
  assert.equal(sent.length, 3, 'identity change after close must not lift');
}

{
  const { controller, sent, update, setNow } = harness('step');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: '4'.repeat(64) });
  assert.equal(controller.advance().ok, true);
  controller.complete('move_l', sent[1].request_id);

  setNow(1400);
  assert.equal(controller.advance().ok, false);
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(sent.length, 2, 'step mode must reauthorize before close');
}

{
  const { controller, sent, update } = harness('auto');
  controller.complete('move_l', sent[0].request_id);
  update({ observedAtMs: 1100, previewId: 'd'.repeat(64), identityId: 'bottle-R3' });
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(controller.snapshot().reason, 'target_identity_changed');
  assert.equal(sent.length, 1);
}

{
  const { controller, sent } = harness('auto');
  controller.cancel('operator_cancelled');
  controller.complete('move_cartesian');
  assert.equal(controller.snapshot().phase, 'aborted');
  assert.equal(sent.length, 1);
}

{
  const sent = [];
  let moving = false;
  const controller = new GraspController({
    sendRobot(command) {
      sent.push(command);
      return true;
    },
    authorizePlan(candidate) {
      return { approved: true, plan: { ...candidate } };
    },
    canContinue() {
      return moving
        ? { approved: false, reason: 'arm_motion_active' }
        : { approved: true };
    },
  });
  controller.updateTarget(target());
  controller.start('auto');
  controller.complete('move_l', sent[0].request_id);
  controller.updateTarget(target({ observedAtMs: 1100, previewId: 'e'.repeat(64) }));
  moving = true;
  controller.complete('move_l', sent[1].request_id);
  assert.equal(controller.snapshot().phase, 'awaiting_robot_idle');
  assert.equal(sent.length, 2);
  moving = false;
  assert.equal(controller.continueWhenIdle(), true);
  assert.equal(sent[2].cmd, 'gripper');
}

console.log('PASS grasp controller keeps staged and auto execution bounded and fail-closed');
