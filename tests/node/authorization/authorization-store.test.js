'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { AuthorizationStore } = require('../../../platform/authorization');
const { digestPlan } = require('../../../platform/authorization/src/canonical-json');

function plan() {
  return {
    schema: 'thirdhand.task-plan.v1',
    taskId: 'task-1',
    planId: 'plan-1',
    revision: 1,
    targetRef: 'robot:gripper',
    risk: 'physical-motion',
    steps: [{ id: 'step-1', skillId: 'manipulation.gripper-control', operation: 'gripper.set' }],
    risks: ['pinch'],
  };
}

test('authorization is exact, expiring, and consumed once', () => {
  let now = Date.parse('2026-09-13T10:00:00.000Z');
  const store = new AuthorizationStore({ clock: () => now, idFactory: () => 'auth-1' });
  const value = plan();
  const digest = digestPlan(value);
  const grant = store.issue({
    plan: value,
    planDigest: digest,
    expiresAt: '2026-09-13T10:00:30.000Z',
    authorizedOperations: ['gripper.set'],
  });
  assert.equal(grant.planDigest, digest);
  assert.equal(store.consume({
    authorizationId: grant.authorizationId,
    plan: value,
    planDigest: digest,
    operation: 'gripper.set',
  }).authorizationId, 'auth-1');
  assert.throws(() => store.consume({
    authorizationId: grant.authorizationId,
    plan: value,
    planDigest: digest,
    operation: 'gripper.set',
  }), error => error.code === 'authorization_consumed');

  now += 60_000;
  const second = store.issue({
    plan: value,
    planDigest: digest,
    expiresAt: '2026-09-13T10:02:00.000Z',
    authorizedOperations: ['gripper.set'],
  });
  assert.throws(() => store.consume({
    authorizationId: second.authorizationId,
    plan: { ...value, revision: 2 },
    planDigest: digest,
    operation: 'gripper.set',
  }), error => error.code === 'plan_digest_mismatch');
});

test('expired, escalated, and revoked grants fail closed', () => {
  let now = Date.parse('2026-09-13T10:00:00.000Z');
  let id = 0;
  const store = new AuthorizationStore({ clock: () => now, idFactory: () => `auth-${++id}` });
  const value = plan();
  const digest = digestPlan(value);
  const issue = expiresAt => store.issue({
    plan: value,
    planDigest: digest,
    expiresAt,
    authorizedOperations: ['gripper.set'],
  });
  const expired = issue('2026-09-13T10:00:01.000Z');
  now += 1001;
  assert.throws(() => store.consume({ authorizationId: expired.authorizationId, plan: value, planDigest: digest, operation: 'gripper.set' }), error => error.code === 'authorization_expired');
  const escalated = issue('2026-09-13T10:01:00.000Z');
  assert.throws(() => store.consume({ authorizationId: escalated.authorizationId, plan: value, planDigest: digest, operation: 'arm.home' }), error => error.code === 'operation_not_authorized');
  const revoked = issue('2026-09-13T10:01:00.000Z');
  store.revokeAll('software_stop');
  assert.throws(() => store.consume({ authorizationId: revoked.authorizationId, plan: value, planDigest: digest, operation: 'gripper.set' }), error => error.code === 'authorization_revoked');
});

test('revoking one authorization does not revoke an independent task', () => {
  const now = Date.parse('2026-09-13T10:00:00.000Z');
  let id = 0;
  const store = new AuthorizationStore({ clock: () => now, idFactory: () => `auth-${++id}` });
  const firstPlan = plan();
  const secondPlan = { ...plan(), taskId: 'task-2', planId: 'plan-2' };
  const first = store.issue({
    plan: firstPlan, planDigest: digestPlan(firstPlan),
    expiresAt: '2026-09-13T10:01:00.000Z', authorizedOperations: ['gripper.set'],
  });
  const second = store.issue({
    plan: secondPlan, planDigest: digestPlan(secondPlan),
    expiresAt: '2026-09-13T10:01:00.000Z', authorizedOperations: ['gripper.set'],
  });

  assert.equal(store.revoke(first.authorizationId, 'operator_cancelled'), true);
  assert.throws(() => store.consume({
    authorizationId: first.authorizationId, plan: firstPlan,
    planDigest: digestPlan(firstPlan), operation: 'gripper.set',
  }), error => error.code === 'authorization_revoked');
  assert.equal(store.consume({
    authorizationId: second.authorizationId, plan: secondPlan,
    planDigest: digestPlan(secondPlan), operation: 'gripper.set',
  }).authorizationId, second.authorizationId);
});
