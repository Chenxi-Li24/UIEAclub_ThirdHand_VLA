'use strict';

const assert = require('assert/strict');
const {
  approvalContentId,
  authorizeActiveViewMove,
  degreesToRadians,
} = require('../active-view-authorization');

const EVIDENCE_A = `sha256:${'a'.repeat(64)}`;
const EVIDENCE_B = `sha256:${'b'.repeat(64)}`;
const SESSION_ID = '11111111-1111-4111-8111-111111111111';
const PROPOSAL_ID = '22222222-2222-4222-8222-222222222222';

const limits = Object.freeze({
  maxSpeedScale: 0.05,
  maxTranslationM: 0.020,
  maxRotationRad: 5 * Math.PI / 180,
  maxRefinementSteps: 3,
  requireStepConfirmation: true,
  robotModelId: 'startouch-fasttouch-v3',
  jointLimitsDeg: [
    [-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164],
  ],
});

function makeApproval(overrides = {}) {
  const payload = {
    schema_version: 1,
    issued_at_ms: 500,
    expires_at_ms: 2_000,
    operator_acknowledged: true,
    robot_model_id: limits.robotModelId,
    evidence_ids: [EVIDENCE_A, EVIDENCE_B],
    limits: {
      max_speed_scale: limits.maxSpeedScale,
      max_translation_m: limits.maxTranslationM,
      max_rotation_rad: limits.maxRotationRad,
      max_refinement_steps: limits.maxRefinementSteps,
      require_step_confirmation: limits.requireStepConfirmation,
    },
    ...overrides,
  };
  delete payload.content_id;
  return { ...payload, content_id: approvalContentId(payload) };
}

function makeProposal(overrides = {}) {
  return {
    trusted: true,
    sessionId: SESSION_ID,
    proposalId: PROPOSAL_ID,
    identityId: 9,
    kind: 'coarse',
    receivedAtMs: 900,
    expiresAtMs: 1_100,
    targetPoseId: 'table_center',
    jointsDeg: [1, 20, -40, 0, 10, 0],
    deltaBaseM: null,
    opticalAxisBase: null,
    rotationDeltaRad: null,
    evidenceIds: [EVIDENCE_A, EVIDENCE_B],
    ...overrides,
  };
}

function makeRobot(overrides = {}) {
  return {
    connected: true,
    moving: false,
    stateFresh: true,
    graspActive: false,
    currentJointsDeg: [1, 15, -35, 0, 8, 0],
    ...overrides,
  };
}

function makeSession(overrides = {}) {
  return {
    sessionId: SESSION_ID,
    proposalId: PROPOSAL_ID,
    identityId: 9,
    evidenceIds: [EVIDENCE_A, EVIDENCE_B],
    refinementSteps: 0,
    activeMotion: false,
    operatorConfirmed: true,
    ...overrides,
  };
}

function decide(overrides = {}) {
  return authorizeActiveViewMove({
    requested: true,
    approval: makeApproval(),
    proposal: makeProposal(),
    robot: makeRobot(),
    session: makeSession(),
    nowMs: 1_000,
    limits,
    ...overrides,
  });
}

assert.deepEqual(
  decide({ requested: false }),
  { approved: false, reason: 'active_view_execution_disabled' }
);
assert.equal(decide().approved, true);
assert.deepEqual(
  decide().command.joints_rad,
  makeProposal().jointsDeg.map(degreesToRadians)
);
assert.equal(decide().command.speed_scale, 0.05);
assert.equal(decide().command.source, 'active_view:coarse');

const rejectionCases = [
  ['approval_missing', { approval: null }],
  ['approval_expired', { nowMs: 2_000 }],
  ['approval_expired', { nowMs: 2_001 }],
  ['approval_duration_invalid', { approval: makeApproval({ expires_at_ms: 500 + 8 * 60 * 60 * 1000 + 1 }) }],
  ['approval_not_acknowledged', { approval: makeApproval({ operator_acknowledged: false }) }],
  ['approval_integrity_invalid', { approval: { ...makeApproval(), expires_at_ms: 1_999 } }],
  ['approval_evidence_mismatch', { approval: makeApproval({ evidence_ids: [EVIDENCE_A] }) }],
  ['approval_limits_mismatch', { approval: makeApproval({ limits: { ...makeApproval().limits, max_speed_scale: 0.04 } }) }],
  ['robot_model_mismatch', { approval: makeApproval({ robot_model_id: 'other-robot' }) }],
  ['session_mismatch', { session: makeSession({ sessionId: '33333333-3333-4333-8333-333333333333' }) }],
  ['identity_mismatch', { proposal: makeProposal({ identityId: 10 }) }],
  ['proposal_mismatch', { session: makeSession({ proposalId: '33333333-3333-4333-8333-333333333333' }) }],
  ['proposal_stale', { proposal: makeProposal({ receivedAtMs: 799, expiresAtMs: 1_200 }) }],
  ['proposal_expired', { proposal: makeProposal({ expiresAtMs: 999 }) }],
  ['robot_not_connected', { robot: makeRobot({ connected: false }) }],
  ['robot_motion_active', { robot: makeRobot({ moving: true }) }],
  ['robot_state_stale', { robot: makeRobot({ stateFresh: false }) }],
  ['grasp_active', { robot: makeRobot({ graspActive: true }) }],
  ['active_view_motion_active', { session: makeSession({ activeMotion: true }) }],
  ['operator_confirmation_required', { session: makeSession({ operatorConfirmed: false }) }],
  ['joint_target_out_of_bounds', { proposal: makeProposal({ jointsDeg: [200, 20, -40, 0, 10, 0] }) }],
  ['all_zero_joint_target_forbidden', { proposal: makeProposal({ jointsDeg: [0, 0, 0, 0, 0, 0] }) }],
];

for (const [reason, overrides] of rejectionCases) {
  assert.deepEqual(decide(overrides), { approved: false, reason }, reason);
}

const unsafeLimits = { ...limits, maxSpeedScale: 0.051 };
assert.deepEqual(
  decide({ limits: unsafeLimits, approval: makeApproval({
    limits: { ...makeApproval().limits, max_speed_scale: 0.051 },
  }) }),
  { approved: false, reason: 'speed_scale_exceeds_hard_limit' }
);

function refinement(overrides = {}) {
  return makeProposal({
    kind: 'refine_delta',
    targetPoseId: null,
    jointsDeg: null,
    deltaBaseM: [0.010, 0, 0],
    opticalAxisBase: [0, 0, 1],
    rotationDeltaRad: [0, 0, 0],
    ...overrides,
  });
}

const acceptedRefinement = decide({ proposal: refinement() });
assert.equal(acceptedRefinement.approved, true);
assert.deepEqual(acceptedRefinement.command.delta_base_m, [0.010, 0, 0]);

assert.deepEqual(
  decide({ proposal: refinement({ deltaBaseM: [0.0201, 0, 0] }) }),
  { approved: false, reason: 'refinement_translation_exceeds_limit' }
);
assert.deepEqual(
  decide({ proposal: refinement({ deltaBaseM: [0, 0, 0.001] }) }),
  { approved: false, reason: 'optical_axis_refinement_forbidden' }
);
assert.deepEqual(
  decide({ proposal: refinement({ rotationDeltaRad: [0, 0, 0.001] }) }),
  { approved: false, reason: 'refinement_rotation_forbidden' }
);
assert.deepEqual(
  decide({ proposal: refinement(), session: makeSession({ refinementSteps: 3 }) }),
  { approved: false, reason: 'refinement_limit_reached' }
);

console.log('PASS active-view authorization is evidence-bound and fail-closed');
