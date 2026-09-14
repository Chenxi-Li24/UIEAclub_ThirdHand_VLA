'use strict';

const assert = require('assert/strict');
const { OpenAIProvider, ProviderError } = require('../vla/openai-provider');

const evidence = {
  frameId: 1842,
  frameMonotonicNs: 987654321,
  observedAtMs: 1000,
  imageSha256: `sha256:${'a'.repeat(64)}`,
  jpeg: Buffer.from([0xff, 0xd8, 0x43, 0x4f, 0x4b, 0x45, 0xff, 0xd9]),
  candidates: [
    { identityId: 12, detectionId: 3, label: 'bottle', identityStatus: 'confirmed', detectionScore: 0.94 },
    { identityId: 15, detectionId: 4, label: 'can', identityStatus: 'confirmed', detectionScore: 0.91 },
  ],
  allowedIdentityIds: [12, 15],
};

const SELECT = {
  decision: 'select', identity_id: 12, ambiguous: false,
  explanation: 'ID 12 是可乐瓶。', semantic_score: 0.91,
};

function apiPayload(decision = SELECT, extra = {}) {
  return {
    id: 'resp_test',
    model: 'gpt-5.6-terra-2026-07-01',
    status: 'completed',
    output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(decision) }] }],
    usage: {
      input_tokens: 100,
      output_tokens: 20,
      input_tokens_details: { cached_tokens: 10 },
    },
    ...extra,
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function sequenceClock(values) {
  let index = 0;
  return () => values[Math.min(index++, values.length - 1)];
}

async function expectProviderError(promise, code) {
  await assert.rejects(promise, error => {
    assert.equal(error instanceof ProviderError, true);
    assert.equal(error.code, code);
    assert.equal(JSON.stringify(error).includes('test-secret'), false);
    return true;
  });
}

(async () => {
  const requests = [];
  const provider = new OpenAIProvider({
    apiKey: 'test-secret',
    model: 'gpt-5.6-terra',
    timeoutMs: 8000,
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return jsonResponse(apiPayload());
    },
    nowMs: sequenceClock([1000, 1120]),
  });
  const result = await provider.select({
    query: '夹取可乐', evidence, signal: new AbortController().signal,
  });
  assert.deepEqual(result, {
    decision: {
      decision: 'select', identityId: 12, ambiguous: false,
      explanation: 'ID 12 是可乐瓶。', semanticScore: 0.91,
    },
    provider: 'openai',
    modelId: 'gpt-5.6-terra-2026-07-01',
    latencyMs: 120,
    usage: { inputTokens: 100, outputTokens: 20, cachedTokens: 10 },
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'https://api.openai.com/v1/responses');
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(requests[0].options.headers.Authorization, 'Bearer test-secret');
  const requestBody = JSON.parse(requests[0].options.body);
  assert.equal(requestBody.model, 'gpt-5.6-terra');
  assert.deepEqual(
    requestBody.text.format.schema.properties.identity_id.anyOf[0].enum,
    [12, 15]
  );

  await expectProviderError(
    new OpenAIProvider({ apiKey: '', fetchImpl: async () => jsonResponse(apiPayload()) })
      .select({ query: 'x', evidence, signal: new AbortController().signal }),
    'provider_unavailable'
  );
  for (const [status, payload, code] of [
    [401, { error: { code: 'invalid_api_key' } }, 'provider_authentication'],
    [429, { error: { code: 'insufficient_quota' } }, 'provider_quota'],
    [429, { error: { code: 'rate_limit_exceeded' } }, 'provider_rate_limit'],
    [500, { error: { code: 'server_error' } }, 'provider_upstream'],
  ]) {
    const failing = new OpenAIProvider({
      apiKey: 'test-secret', fetchImpl: async () => jsonResponse(payload, status),
    });
    await expectProviderError(
      failing.select({ query: 'x', evidence, signal: new AbortController().signal }),
      code
    );
  }

  for (const [response, code] of [
    [new Response('{broken', { status: 200 }), 'provider_response_invalid'],
    [jsonResponse(apiPayload(SELECT, { output: [] })), 'provider_output_missing'],
    [jsonResponse(apiPayload(SELECT, { status: 'incomplete' })), 'provider_incomplete'],
    [jsonResponse(apiPayload(SELECT, { status: 'failed' })), 'provider_incomplete'],
    [jsonResponse(apiPayload(SELECT, { status: 'cancelled' })), 'provider_incomplete'],
    [jsonResponse(apiPayload(SELECT, {
      output: [{ type: 'message', content: [
        { type: 'output_text', text: JSON.stringify(SELECT) },
        { type: 'refusal', refusal: 'cannot comply' },
      ] }],
    })), 'provider_refusal'],
    [jsonResponse(apiPayload(SELECT, {
      output: [{ type: 'message', content: [
        { type: 'output_text', text: JSON.stringify(SELECT) },
        { type: 'output_text', text: JSON.stringify(SELECT) },
      ] }],
    })), 'provider_output_invalid'],
    [jsonResponse(apiPayload({ ...SELECT, identity_id: 99 })), 'identity_not_allowed'],
    [new Response('x'.repeat(70_000), { status: 200 }), 'provider_response_too_large'],
  ]) {
    const failing = new OpenAIProvider({ apiKey: 'test-secret', fetchImpl: async () => response });
    await expectProviderError(
      failing.select({ query: 'x', evidence, signal: new AbortController().signal }),
      code
    );
  }

  const cancelled = new AbortController();
  cancelled.abort();
  await expectProviderError(
    provider.select({ query: 'x', evidence, signal: cancelled.signal }),
    'request_cancelled'
  );

  const timeout = new OpenAIProvider({
    apiKey: 'test-secret', timeoutMs: 5,
    fetchImpl: async (_url, options) => new Promise((resolve, reject) => {
      const keepAlive = setTimeout(() => resolve(jsonResponse(apiPayload())), 100);
      options.signal.addEventListener('abort', () => {
        clearTimeout(keepAlive);
        reject(options.signal.reason);
      }, { once: true });
    }),
  });
  await expectProviderError(
    timeout.select({ query: 'x', evidence, signal: new AbortController().signal }),
    'provider_timeout'
  );

  const bodyTimeout = new OpenAIProvider({
    apiKey: 'test-secret', timeoutMs: 5,
    fetchImpl: async (_url, options) => new Response(new ReadableStream({
      start(controller) {
        const keepAlive = setTimeout(() => controller.close(), 100);
        options.signal.addEventListener('abort', () => {
          clearTimeout(keepAlive);
          controller.error(options.signal.reason);
        }, { once: true });
      },
    })),
  });
  await expectProviderError(
    bodyTimeout.select({ query: 'x', evidence, signal: new AbortController().signal }),
    'provider_timeout'
  );

  const bodyCancelled = new AbortController();
  const cancelledBodyProvider = new OpenAIProvider({
    apiKey: 'test-secret', timeoutMs: 1000,
    fetchImpl: async (_url, options) => new Response(new ReadableStream({
      start(controller) {
        const keepAlive = setTimeout(() => controller.close(), 100);
        options.signal.addEventListener('abort', () => {
          clearTimeout(keepAlive);
          controller.error(options.signal.reason);
        }, { once: true });
      },
    })),
  });
  const cancelledBody = cancelledBodyProvider.select({
    query: 'x', evidence, signal: bodyCancelled.signal,
  });
  setTimeout(() => bodyCancelled.abort(), 0);
  await expectProviderError(cancelledBody, 'request_cancelled');

  console.log('PASS OpenAI provider is bounded, cancellable, strict, and secret-safe');
})().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
