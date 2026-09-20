'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { BottlePickAdapter } = require(
  '../../../apps/web/src/language/bottle-pick-adapter',
);

function json(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function request(events) {
  return {
    candidate: {
      candidateId: 'candidate-1',
      traceId: 'trace-1',
    },
    emit: event => events.push(event),
  };
}

test('bottle pick adapter binds the selected vision target to one VA request', async () => {
  const calls = [];
  const events = [];
  const adapter = new BottlePickAdapter({
    requestIdFactory: () => 'request-1',
    pollIntervalMs: 0,
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      if (url.endsWith('/api/vision/observation')) {
        return json({ selectedStableId: 3, targets: [{ stableId: 3 }] });
      }
      if (url.endsWith('/api/va/start')) {
        return json({ accepted: true }, 202);
      }
      if (url.endsWith('/api/va/status')) {
        return json({ active: false, phase: 'complete' });
      }
      throw new Error(`unexpected URL ${url}`);
    },
  });

  const result = await adapter.start(request(events));
  assert.equal(result.accepted, true);
  assert.equal(result.completed, true);
  assert.equal(calls.length, 3);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    schema: 'thirdhand.va.command.v1',
    cmd: 'start',
    target_id: 3,
    request_id: 'request-1',
  });
  assert.equal(events[0].type, 'skill.execution.started');
  assert.equal(events.at(-1).type, 'skill.result');
  assert.equal(events.at(-1).success, true);
});

test('bottle pick adapter fails closed without a selected stable target', async () => {
  const events = [];
  const adapter = new BottlePickAdapter({
    fetchImpl: async () => json({ selectedStableId: null, targets: [] }),
  });

  const result = await adapter.start(request(events));
  assert.equal(result.accepted, false);
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'skill.result');
  assert.equal(events[0].success, false);
  assert.match(events[0].message, /选择一个稳定瓶子目标/);
});
