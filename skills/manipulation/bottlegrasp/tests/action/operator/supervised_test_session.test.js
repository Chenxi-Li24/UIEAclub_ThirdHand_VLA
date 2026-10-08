'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { SupervisedTestSession } = require('../../../src/thirdhand_va/action/operator/supervised_test_session');

function fixturePlan() {
  return {
    schema: 'thirdhand-execution-plan-v2', stableId: 1, requestId: 'req-1',
    evidenceId: `sha256:${'a'.repeat(64)}`, motionEpoch: 0,
    pregraspSegments: [{ position: [0.3, 0, 0.2], timeSec: 3 }],
    finalApproachM: [0.4, 0, 0.2], liftM: [0.4, 0, 0.3],
    prePlaceM: [0.5, -0.2, 0.3], placeM: [0.5, -0.2, 0.2],
    retreatM: [0.5, -0.2, 0.3], graspEulerRad: [0, 0, 0],
    placeEulerRad: [0, 0, 0], homePreset: 'home',
    homeJointsDeg: [0, 0, 0, 0, 0, 0], homeToleranceDeg: 0.5,
    widthM: 0.05, contactMinWidthM: 0.008, contactMaxWidthM: 0.07,
    releaseMinWidthM: 0.074, releaseMaxWidthM: 0.08,
    timeSecByPhase: { final_approach: 3, lift: 3, transfer: 3, lower: 3, retreat: 3 },
    transferSegments: [{ position: [0.5, -0.2, 0.3], timeSec: 3 }],
    openPosition: 1, closePosition: 0,
    pathValidationId: `sha256:${'b'.repeat(64)}`,
  };
}

function harness({ executable = true } = {}) {
  const sent = [];
  let now = 1000;
  let evidence = { targetId: 1, frameId: 4, motionEpoch: 0, robotStateSequence: 1 };
  const preview = {
    previewId: `sha256:${'c'.repeat(64)}`, targetId: 1,
    createdAtMs: 1000, expiresAtMs: 2000,
    executable, blockers: executable ? [] : ['calibration_not_approved'],
    evidence, plan: executable ? fixturePlan() : null,
  };
  const session = new SupervisedTestSession({
    previewFactory: () => preview,
    currentEvidence: () => evidence,
    getRobotState: () => ({ connected: true, healthy: true, stateFresh: true }),
    robotClient: { send(command) { sent.push(command); return true; } },
    nowMs: () => now,
    commandTimeoutMs: 1000,
  });
  return { session, sent, preview, setNow: value => { now = value; },
    setEvidence: value => { evidence = value; } };
}

test('blocked preview cannot create a motion-capable session', () => {
  const h = harness({ executable: false });
  h.session.preview(1);
  assert.equal(h.session.start({ requestId: 'req-1', previewId: h.preview.previewId }).accepted, false);
  assert.equal(h.sent.length, 0);
});

test('start is read-only and each confirmation sends only one correlated command', () => {
  const h = harness();
  h.session.preview(1);
  assert.equal(h.session.start({ requestId: 'req-1', previewId: h.preview.previewId }).phase,
    'awaiting_confirmation');
  assert.equal(h.sent.length, 0);
  const first = h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'confirm-1' });
  assert.equal(first.accepted, true);
  assert.equal(h.sent.length, 1);
  assert.deepEqual(h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'confirm-1' }), first);
  assert.equal(h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'confirm-2' }).accepted, false);
  const command = h.sent[0];
  h.session.onRobotEvent({ type: 'command_complete', command: command.cmd,
    request_id: command.request_id, reached: true });
  assert.equal(h.sent.length, 1);
  assert.equal(h.session.snapshot().commandPhase, 'pregrasp');
  assert.equal(h.session.snapshot().awaiting_confirmation, true);
});

test('stale preview and changed evidence block advancement', () => {
  const h = harness();
  h.session.preview(1);
  h.session.start({ requestId: 'req-1', previewId: h.preview.previewId });
  h.setEvidence({ ...h.preview.evidence, robotStateSequence: 2 });
  assert.equal(h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'confirm-1' }).accepted, false);
  assert.equal(h.sent.length, 0);
});

test('timed-out command requests stop and remains uncertain until stop acknowledgment', () => {
  const h = harness();
  h.session.preview(1);
  h.session.start({ requestId: 'req-1', previewId: h.preview.previewId });
  h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'confirm-1' });
  h.setNow(2200);
  h.session.checkTimeout();
  assert.equal(h.sent.at(-1).cmd, 'software_stop');
  assert.equal(h.session.snapshot().phase, 'uncertain_stop');
  h.session.onRobotEvent({ type: 'software_stop_complete', request_id: h.sent.at(-1).request_id });
  assert.equal(h.session.snapshot().phase, 'stopped');
});

test('requesting another preview cannot replace evidence for an active session', () => {
  const h = harness();
  h.session.preview(1);
  h.session.start({ requestId: 'req-1', previewId: h.preview.previewId });
  assert.throws(() => h.session.preview(2), /session_active/);
  assert.equal(h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'one' }).accepted, true);
  assert.equal(h.sent.length, 1);
});

test('reusing a confirmation ID for another phase does not authorize motion', () => {
  const h = harness();
  h.session.preview(1);
  h.session.start({ requestId: 'req-1', previewId: h.preview.previewId });
  h.session.next({ requestId: 'req-1', expectedPhase: 'open', confirmationId: 'one' });
  const command = h.sent[0];
  h.session.onRobotEvent({ type: 'command_complete', command: command.cmd,
    request_id: command.request_id, reached: true });
  assert.equal(h.session.next({ requestId: 'req-1', expectedPhase: 'pregrasp', confirmationId: 'one' }).accepted, false);
  assert.equal(h.sent.length, 1);
});
