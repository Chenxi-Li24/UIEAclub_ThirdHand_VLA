'use strict';

const assert = require('assert/strict');
const {
  authorizeActiveViewStart,
  parseActiveViewBrowserCommand,
} = require('../active-view-browser-protocol');

const SESSION_ID = '11111111-1111-4111-8111-111111111111';
const PROPOSAL_ID = '22222222-2222-4222-8222-222222222222';

assert.deepEqual(
  parseActiveViewBrowserCommand({ cmd: 'start_active_view', identityId: 7 }),
  { accepted: true, command: 'start', identityId: 7 }
);
assert.deepEqual(
  parseActiveViewBrowserCommand({
    cmd: 'confirm_active_view_step', sessionId: SESSION_ID, proposalId: PROPOSAL_ID,
  }),
  { accepted: true, command: 'confirm', sessionId: SESSION_ID, proposalId: PROPOSAL_ID }
);
assert.deepEqual(
  parseActiveViewBrowserCommand({ cmd: 'cancel_active_view', sessionId: SESSION_ID }),
  { accepted: true, command: 'cancel', sessionId: SESSION_ID }
);

for (const injected of [
  { cmd: 'start_active_view', identityId: 7, x: 0.1 },
  { cmd: 'confirm_active_view_step', sessionId: SESSION_ID, proposalId: PROPOSAL_ID, joints: [0, 0, 0, 0, 0, 0] },
  { cmd: 'cancel_active_view', sessionId: SESSION_ID, position: [0, 0, 0] },
]) {
  assert.deepEqual(
    parseActiveViewBrowserCommand(injected),
    { accepted: false, reason: 'browser_command_keys_invalid' }
  );
}

const trustedTargets = [{ identityId: 7, label: 'bottle' }];
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 8, trustedTargets, activeViewActive: false, graspActive: false, motionActive: false,
  }),
  { approved: false, reason: 'identity_not_fresh_or_confirmed' }
);
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 7, trustedTargets: [], activeViewActive: false, graspActive: false, motionActive: false,
  }),
  { approved: false, reason: 'identity_not_fresh_or_confirmed' }
);
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 7, trustedTargets, activeViewActive: false, graspActive: true, motionActive: false,
  }),
  { approved: false, reason: 'grasp_active' }
);
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 7, trustedTargets, activeViewActive: false, graspActive: false, motionActive: true,
  }),
  { approved: false, reason: 'robot_motion_active' }
);
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 7, trustedTargets, activeViewActive: true, graspActive: false, motionActive: false,
  }),
  { approved: false, reason: 'active_view_session_active' }
);
assert.deepEqual(
  authorizeActiveViewStart({
    identityId: 7, trustedTargets, activeViewActive: false, graspActive: false, motionActive: false,
  }),
  { approved: true, identityId: 7 }
);

console.log('PASS active-view browser protocol is ID-only and mutually exclusive');
