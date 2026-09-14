'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { execute } = require('../../../skills/manipulation/gripper-control/src/worker');

function fixture() {
  const plan = {
    schema: 'thirdhand.task-plan.v1', taskId: 'task-1', planId: 'plan-1', revision: 1,
    targetRef: 'robot:gripper', risk: 'physical-motion',
    steps: [{ id: 'step-1', skillId: 'manipulation.gripper-control', operation: 'gripper.set', parameters: { positionPercent: 100, tolerancePercent: 2, timeoutMs: 3000 } }],
    risks: ['pinch'],
  };
  const authorization = {
    schema: 'thirdhand.task-authorization.v2', authorizationId: 'auth-1', taskId: 'task-1', planId: 'plan-1', planRevision: 1,
    targetRef: 'robot:gripper', planDigest: `sha256:${'b'.repeat(64)}`, authorizedOperations: ['gripper.set'],
    issuedAt: '2026-09-13T10:00:00.000Z', expiresAt: '2026-09-13T10:00:30.000Z',
  };
  return { plan, authorization };
}

test('worker builds one exact primitive and maps feedback to SkillResult', async () => {
  const sent = [];
  const robotClient = {
    execute: async primitive => {
      sent.push(primitive);
      return { status: 'completed', actualPercent: 99.4, maxJointDeltaDeg: 0.1 };
    },
  };
  const { plan, authorization } = fixture();
  const result = await execute({ plan, authorization, traceId: 'trace-1', robotClient, idFactory: () => 'primitive-1' });
  assert.equal(sent.length, 1);
  assert.equal(sent[0].operation, 'gripper.set');
  assert.deepEqual(sent[0].parameters, plan.steps[0].parameters);
  assert.equal(result.status, 'completed');
  assert.equal(result.output.actualPercent, 99.4);
});

test('worker reports uncertain Robot result as interrupted and never retries', async () => {
  let calls = 0;
  const robotClient = { execute: async () => { calls += 1; return { status: 'uncertain', code: 'feedback_timeout' }; } };
  const { plan, authorization } = fixture();
  const result = await execute({ plan, authorization, traceId: 'trace-1', robotClient, idFactory: () => 'primitive-1' });
  assert.equal(calls, 1);
  assert.equal(result.status, 'interrupted');
  assert.equal(result.reason.code, 'feedback_timeout');
});
