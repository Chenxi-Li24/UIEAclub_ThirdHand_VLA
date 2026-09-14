'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { main } = require('../../apps/bottle_pick/run');

test('application is a thin stable-ID client for the loopback VA API', async () => {
  const calls = [];
  const output = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options, body: JSON.parse(options.body) });
    return { status: 202, async json() { return { accepted: true }; } };
  };
  const dependencies = {
    fetchImpl,
    baseUrl: 'http://127.0.0.1:8766',
    requestIdFactory: () => 'req-cli',
    write: line => output.push(line),
  };

  assert.equal(await main(['start', '2'], dependencies), 0);
  assert.equal(await main(['stop'], dependencies), 0);
  assert.equal(calls[0].url, 'http://127.0.0.1:8766/api/va/start');
  assert.deepEqual(calls[0].body, {
    schema: 'thirdhand.va.command.v1', cmd: 'start',
    target_id: 2, request_id: 'req-cli',
  });
  assert.equal(calls[1].body.cmd, 'stop');
  assert.equal(JSON.parse(output[0]).accepted, true);
});

test('application rejects invalid action and target before network access', async () => {
  const errors = [];
  let calls = 0;
  const dependencies = {
    fetchImpl: async () => { calls += 1; },
    writeError: line => errors.push(line),
  };
  assert.equal(await main(['launch'], dependencies), 2);
  assert.equal(await main(['start', '6'], dependencies), 2);
  assert.equal(calls, 0);
  assert.match(errors[0], /start <1..5>/);
});
