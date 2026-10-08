'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { main } = require('../../../scripts/action/supervised_test_grasp');

test('test-grasp CLI only performs read-only requests', async () => {
  const requests = [];
  const output = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, method: options?.method ?? 'GET' });
    return { ok: true, json: async () => ({ blockers: ['execution_disabled'] }) };
  };
  assert.equal(await main(['preview', '--target-id', '1'], {
    fetchImpl, write: line => output.push(line), baseUrl: 'http://127.0.0.1:8766',
  }), 0);
  assert.deepEqual(requests.map(request => request.method), ['GET']);
  assert.match(requests[0].url, /\/api\/va\/test\/preview\?target_id=1$/);
  assert.match(output[0], /execution_disabled/);
});

test('test-grasp CLI rejects invalid target IDs and motion verbs', async () => {
  const calls = [];
  const fetchImpl = async () => { calls.push(1); throw new Error('must not call'); };
  assert.equal(await main(['preview', '--target-id', '0'], { fetchImpl, writeError() {} }), 2);
  assert.equal(await main(['next'], { fetchImpl, writeError() {} }), 2);
  assert.equal(calls.length, 0);
});
