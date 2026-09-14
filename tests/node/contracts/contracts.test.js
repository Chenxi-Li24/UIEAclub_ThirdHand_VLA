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

test('authorization v2 binds the canonical plan digest and operation', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.task-authorization.v2', {
    schema: 'thirdhand.task-authorization.v2',
    authorizationId: 'auth-2',
    taskId: 'task-2',
    planId: 'plan-2',
    planRevision: 1,
    targetRef: 'robot:gripper',
    planDigest: `sha256:${'a'.repeat(64)}`,
    authorizedOperations: ['gripper.set'],
    issuedAt: '2026-09-13T10:00:00.000Z',
    expiresAt: '2026-09-13T10:00:30.000Z',
  });
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});

test('execution primitive rejects undeclared operations and extra fields', () => {
  const contracts = createContractValidator();
  const base = {
    schema: 'thirdhand.execution-primitive.v1',
    primitiveId: 'primitive-1',
    traceId: 'trace-1',
    taskId: 'task-1',
    authorizationId: 'auth-1',
    planDigest: `sha256:${'b'.repeat(64)}`,
    operation: 'gripper.set',
    parameters: { positionPercent: 100, tolerancePercent: 2, timeoutMs: 3000 },
  };
  assert.equal(contracts.validate('thirdhand.execution-primitive.v1', base).ok, true);
  assert.equal(contracts.validate('thirdhand.execution-primitive.v1', {
    ...base,
    operation: 'arm.home',
  }).ok, false);
  assert.equal(contracts.validate('thirdhand.execution-primitive.v1', {
    ...base,
    parameters: { ...base.parameters, retry: true },
  }).ok, false);
});

test('plan proposal contains an immutable server plan and readiness snapshot', () => {
  const contracts = createContractValidator();
  const result = contracts.validate('thirdhand.plan-proposal.v1', {
    schema: 'thirdhand.plan-proposal.v1',
    proposalId: 'proposal-1',
    candidateId: 'candidate-1',
    traceId: 'trace-1',
    planDigest: `sha256:${'c'.repeat(64)}`,
    expiresAt: '2026-09-13T10:00:30.000Z',
    plan: {
      schema: 'thirdhand.task-plan.v1',
      taskId: 'task-1',
      planId: 'plan-1',
      revision: 1,
      targetRef: 'robot:gripper',
      risk: 'physical-motion',
      steps: [{
        id: 'step-1',
        skillId: 'manipulation.gripper-control',
        operation: 'gripper.set',
        parameters: { positionPercent: 100, tolerancePercent: 2, timeoutMs: 3000 },
      }],
      risks: ['夹爪运动可能造成夹伤或挤压。'],
    },
    readiness: {
      robot: { reachable: true, connected: true, stateReady: true, moving: false, fresh: true },
      skill: { id: 'manipulation.gripper-control', available: true },
      authorizationReady: true,
      capturedAt: '2026-09-13T10:00:00.000Z',
    },
    risks: ['夹爪运动可能造成夹伤或挤压。'],
  });
  assert.equal(result.ok, true, JSON.stringify(result.errors));
});
