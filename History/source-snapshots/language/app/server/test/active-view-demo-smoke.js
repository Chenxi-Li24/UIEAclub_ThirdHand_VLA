'use strict';

const assert = require('assert/strict');
const { createActiveViewDemo } = require('../../web/active-view-demo');

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$/;

const demo = createActiveViewDemo();
const initial = demo.snapshot();
assert.equal(initial.online, true);
assert.equal(initial.robotExecutionEnabled, false);
assert.equal(initial.activeViewExecutionEnabled, false);
assert.equal(initial.activeView.control.phase, 'idle');
assert.equal(initial.targets[0].identityId, 7);
assert.equal(initial.targets[0].identityStatus, 'confirmed');
assert.equal(initial.targets[0].identityMemory.appearanceSimilarity, 0.93);
assert.match(demo.cameraPanels.lumos, /^data:image\/svg\+xml/);
assert.match(demo.cameraPanels.d435, /^data:image\/svg\+xml/);

let notifications = 0;
const unsubscribe = demo.subscribe(() => { notifications += 1; });

assert.deepEqual(
  demo.send({ cmd: 'start_active_view', identityId: 7, x: 0.1 }),
  { accepted: false, reason: 'browser_command_keys_invalid' }
);
assert.equal(demo.snapshot().activeView.control.phase, 'idle');

const started = demo.send({ cmd: 'start_active_view', identityId: 7 });
assert.equal(started.accepted, true);
assert.equal(started.action, 'start');
assert.match(started.sessionId, UUID);
const coarse = demo.snapshot();
assert.equal(coarse.activeView.control.phase, 'waiting_operator_confirmation');
assert.equal(coarse.activeView.control.moveReady, true);
assert.equal(coarse.activeView.reports[0].kind, 'coarse_pose');
assert.equal(coarse.activeView.reports[0].stableSamples, 0);
assert.match(coarse.activeView.control.proposalId, UUID);
assert.equal(notifications, 1);

assert.deepEqual(
  demo.send({
    cmd: 'confirm_active_view_step',
    sessionId: coarse.activeView.control.sessionId,
    proposalId: '44444444-4444-4444-8444-444444444444',
  }),
  { accepted: false, reason: 'proposal_id_mismatch' }
);

const first = demo.send({
  cmd: 'confirm_active_view_step',
  sessionId: coarse.activeView.control.sessionId,
  proposalId: coarse.activeView.control.proposalId,
});
assert.equal(first.accepted, true);
assert.equal(first.action, 'confirm');
const refine = demo.snapshot();
assert.equal(refine.activeView.control.phase, 'waiting_operator_confirmation');
assert.equal(refine.activeView.control.moveReady, true);
assert.notEqual(refine.activeView.control.proposalId, coarse.activeView.control.proposalId);
assert.equal(refine.activeView.reports[0].kind, 'refine_delta');
assert.equal(refine.activeView.reports[0].stableSamples, 2);
assert.equal(refine.activeView.reports[0].centralFraction, 0.48);
assert.equal(refine.activeView.reports[0].depthAcceptable, false);
assert.equal(notifications, 2);

assert.deepEqual(
  demo.send({
    cmd: 'confirm_active_view_step',
    sessionId: refine.activeView.control.sessionId,
    proposalId: coarse.activeView.control.proposalId,
  }),
  { accepted: false, reason: 'proposal_id_mismatch' }
);

const second = demo.send({
  cmd: 'confirm_active_view_step',
  sessionId: refine.activeView.control.sessionId,
  proposalId: refine.activeView.control.proposalId,
});
assert.equal(second.accepted, true);
const preview = demo.snapshot();
assert.equal(preview.activeView.control.phase, 'grasp_preview');
assert.equal(preview.activeView.control.moveReady, false);
assert.equal(preview.activeView.reports[0].stableSamples, 5);
assert.equal(preview.activeView.reports[0].centralFraction, 0.92);
assert.equal(preview.activeView.reports[0].depthAcceptable, true);
assert.deepEqual(preview.targets[0].positionM, [0.342, -0.118, 0.041]);
assert.equal(preview.robotExecutionEnabled, false);
assert.equal(preview.activeViewExecutionEnabled, false);
assert.equal(notifications, 3);

assert.deepEqual(
  demo.send({
    cmd: 'confirm_active_view_step',
    sessionId: preview.activeView.control.sessionId,
    proposalId: refine.activeView.control.proposalId,
  }),
  { accepted: false, reason: 'confirmation_not_expected' }
);

unsubscribe();

const cancelledDemo = createActiveViewDemo();
const cancelledStart = cancelledDemo.send({ cmd: 'start_active_view', identityId: 7 });
assert.equal(cancelledStart.accepted, true);
assert.equal(
  cancelledDemo.send({ cmd: 'cancel_active_view', sessionId: cancelledStart.sessionId }).accepted,
  true
);
const cancelled = cancelledDemo.snapshot();
assert.equal(cancelled.activeView.control.phase, 'aborted');
assert.deepEqual(cancelled.activeView.control.reasons, ['operator_cancelled']);
assert.equal(cancelled.robotExecutionEnabled, false);
assert.equal(cancelled.activeViewExecutionEnabled, false);

console.log('PASS active-view browser demo is deterministic and fail-closed');
