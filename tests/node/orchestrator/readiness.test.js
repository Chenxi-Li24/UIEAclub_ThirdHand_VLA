'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createReadinessProvider } = require('../../../apps/orchestrator/src/readiness');

test('readiness requires connected fresh idle Robot execution', async () => {
  const now = 1_800_000_000_000;
  const provider = createReadinessProvider({
    robotHealthUrl: 'http://robot/health',
    clock: () => now,
    fetchImpl: async () => ({
      ok: true,
      json: async () => ({
        robot: { connected: true, stateReady: true, moving: false, lastStateAt: now - 100 },
        execution: { available: true, reason: null },
      }),
    }),
  });
  const readiness = await provider();
  assert.equal(readiness.authorizationReady, true);
  assert.equal(readiness.robot.fresh, true);
  assert.equal(readiness.skill.available, true);
});

test('stale or unreachable Robot fails closed', async () => {
  const now = 1_800_000_000_000;
  const stale = createReadinessProvider({
    robotHealthUrl: 'http://robot/health', clock: () => now,
    fetchImpl: async () => ({ ok: true, json: async () => ({
      robot: { connected: true, stateReady: true, moving: false, lastStateAt: now - 501 },
      execution: { available: true },
    }) }),
  });
  assert.equal((await stale()).authorizationReady, false);

  const unreachable = createReadinessProvider({
    robotHealthUrl: 'http://robot/health', clock: () => now,
    fetchImpl: async () => { throw new Error('offline'); },
  });
  assert.equal((await unreachable()).robot.reachable, false);
  assert.equal((await unreachable()).authorizationReady, false);
});
