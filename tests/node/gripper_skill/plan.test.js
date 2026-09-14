'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createContractValidator } = require('../../../platform/contracts/src/validator');
const { createGripperProposal } = require('../../../skills/manipulation/gripper-control/src/plan');

function readiness(capturedAt) {
  return {
    robot: { reachable: true, connected: true, stateReady: true, moving: false, fresh: true },
    skill: { id: 'manipulation.gripper-control', available: true },
    authorizationReady: true,
    capturedAt,
  };
}

test('open and close create one exact server-owned gripper step', () => {
  const now = Date.parse('2026-09-13T10:00:00.000Z');
  let id = 0;
  const options = { clock: () => now, idFactory: () => `id-${++id}`, readiness: readiness(new Date(now).toISOString()) };
  const open = createGripperProposal({ candidateId: 'c1', traceId: 't1', intent: 'gripper.open', source: 'voice', transcript: '打开夹爪', parameters: { positionPercent: 7 } }, options);
  const close = createGripperProposal({ candidateId: 'c2', traceId: 't2', intent: 'gripper.close', source: 'text', transcript: '关闭夹爪' }, options);

  assert.deepEqual(open.plan.steps[0].parameters, { positionPercent: 100, tolerancePercent: 2, timeoutMs: 3000 });
  assert.deepEqual(close.plan.steps[0].parameters, { positionPercent: 0, tolerancePercent: 2, timeoutMs: 3000 });
  assert.equal(open.plan.steps.length, 1);
  assert.equal(open.plan.targetRef, 'robot:gripper');
  assert.equal(open.plan.risks.length, 1);
  const contracts = createContractValidator();
  assert.equal(contracts.validate('thirdhand.plan-proposal.v1', open).ok, true);
});

test('unsupported intent fails closed', () => {
  assert.throws(() => createGripperProposal({ candidateId: 'c1', traceId: 't1', intent: 'arm.home', source: 'voice', transcript: '回零' }, {
    clock: () => Date.now(), idFactory: () => 'id', readiness: readiness(new Date().toISOString()),
  }), error => error.code === 'unsupported_intent');
});
