'use strict';

const assert = require('assert/strict');
const { MockProvider } = require('../vla/mock-provider');

const evidence = {
  candidates: [
    { identityId: 12, detectionId: 3, label: 'bottle', identityStatus: 'confirmed', detectionScore: 0.94 },
    { identityId: 15, detectionId: 4, label: 'can', identityStatus: 'confirmed', detectionScore: 0.91 },
  ],
  allowedIdentityIds: [12, 15],
};

(async () => {
  const selected = await new MockProvider({ identityId: 12 }).select({
    query: '夹取可乐', evidence, signal: new AbortController().signal,
  });
  assert.deepEqual(selected.decision, {
    decision: 'select', identityId: 12, ambiguous: false,
    explanation: 'Mock provider selected ID 12.', semanticScore: 1,
  });
  assert.equal(selected.provider, 'mock');
  assert.equal(selected.modelId, 'mock-v1');
  assert.deepEqual(selected.usage, { inputTokens: 0, outputTokens: 0, cachedTokens: 0 });

  const none = await new MockProvider().select({
    query: '夹取可乐', evidence, signal: new AbortController().signal,
  });
  assert.equal(none.decision.decision, 'none');
  assert.equal(none.decision.identityId, null);

  await assert.rejects(
    new MockProvider({ identityId: 99 }).select({
      query: 'x', evidence, signal: new AbortController().signal,
    }),
    /identity_not_allowed/
  );

  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    new MockProvider({ identityId: 12 }).select({ query: 'x', evidence, signal: controller.signal }),
    error => error.code === 'request_cancelled'
  );

  console.log('PASS mock provider is deterministic, ID-bounded, and network-free');
})().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
