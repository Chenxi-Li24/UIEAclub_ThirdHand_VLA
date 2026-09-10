const test = require('node:test');
const assert = require('node:assert/strict');
const { createContractValidator } = require('../../../platform/contracts/src/validator');

test('task authorization is bound to plan revision and target', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.task-authorization.v1', {
    schema: 'thirdhand.task-authorization.v1',
    authorizationId: 'auth-1',
    taskId: 'task-1',
    planId: 'plan-1',
    planRevision: 2,
    targetRef: 'target-7',
    expiresAt: '2026-09-10T13:00:00+08:00',
  });
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test('physical plan without risks is rejected', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.task-plan.v1', {
    schema: 'thirdhand.task-plan.v1',
    taskId: 'task-1',
    planId: 'plan-1',
    revision: 1,
    targetRef: 'target-7',
    risk: 'physical-motion',
    steps: [{ id: 'step-1', skillId: 'manipulation.pick-and-place' }],
    risks: [],
  });
  assert.equal(result.ok, false);
});

test('unknown schema IDs fail closed', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.unknown.v1', {});
  assert.equal(result.ok, false);
  assert.equal(result.errors[0].keyword, 'unknown_schema');
});
