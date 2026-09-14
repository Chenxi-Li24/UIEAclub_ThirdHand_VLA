'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { AuthorizationStore } = require('../../../platform/authorization');
const { TaskEngine } = require('../../../platform/task_engine');
const { createGripperProposal } = require('../../../skills/manipulation/gripper-control/src/plan');

function setup() {
  const now = Date.parse('2026-09-13T10:00:00.000Z');
  let id = 0;
  const clock = () => now;
  const idFactory = () => `id-${++id}`;
  const proposal = createGripperProposal({
    candidateId: 'candidate-1', traceId: 'trace-1', intent: 'gripper.open', source: 'voice', transcript: '打开夹爪',
  }, {
    clock,
    idFactory,
    readiness: {
      robot: { reachable: true, connected: true, stateReady: true, moving: false, fresh: true },
      skill: { id: 'manipulation.gripper-control', available: true },
      authorizationReady: true,
      capturedAt: new Date(now).toISOString(),
    },
  });
  const worker = {
    execute: async ({ plan, authorization }) => ({
      schema: 'thirdhand.skill-result.v1',
      taskId: plan.taskId,
      traceId: proposal.traceId,
      skillId: 'manipulation.gripper-control',
      status: 'completed',
      reason: { code: 'target_reached', message: authorization.authorizationId },
      output: {},
    }),
  };
  const authorizationStore = new AuthorizationStore({ clock, idFactory });
  const engine = new TaskEngine({
    authorizationStore,
    resolveSkill: () => worker,
    readinessProvider: async () => proposal.readiness,
    clock,
  });
  return { engine, proposal };
}

test('task requires one grant and reaches completed through its worker', async () => {
  const { engine, proposal } = setup();
  engine.registerProposal({ proposal });
  await assert.rejects(engine.executeAuthorized({ authorizationId: 'missing' }), error => error.code === 'authorization_unknown');
  const grant = await engine.grantAuthorization({
    proposalId: proposal.proposalId,
    planId: proposal.plan.planId,
    planRevision: proposal.plan.revision,
    planDigest: proposal.planDigest,
  });
  const result = await engine.executeAuthorized({ authorizationId: grant.authorizationId });
  assert.equal(result.status, 'completed');
  assert.equal(engine.getTask(proposal.plan.taskId).state, 'completed');
  await assert.rejects(engine.executeAuthorized({ authorizationId: grant.authorizationId }), error => error.code === 'invalid_task_transition');
});

test('changed digest and unavailable readiness reject authorization', async () => {
  const { engine, proposal } = setup();
  engine.registerProposal({ proposal });
  await assert.rejects(engine.grantAuthorization({
    proposalId: proposal.proposalId,
    planId: proposal.plan.planId,
    planRevision: proposal.plan.revision,
    planDigest: `sha256:${'0'.repeat(64)}`,
  }), error => error.code === 'plan_digest_mismatch');
});

test('invalid Skill results fail the task instead of being reported to the browser', async () => {
  const { engine, proposal } = setup();
  engine.resolveSkill = () => ({ execute: async () => ({ status: 'completed' }) });
  engine.registerProposal({ proposal });
  const grant = await engine.grantAuthorization({
    proposalId: proposal.proposalId,
    planId: proposal.plan.planId,
    planRevision: proposal.plan.revision,
    planDigest: proposal.planDigest,
  });
  await assert.rejects(
    engine.executeAuthorized({ authorizationId: grant.authorizationId }),
    error => error.code === 'skill_result_invalid',
  );
  assert.equal(engine.getTask(proposal.plan.taskId).state, 'failed');
});
