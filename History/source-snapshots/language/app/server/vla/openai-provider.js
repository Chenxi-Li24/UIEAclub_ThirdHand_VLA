'use strict';

const { buildOpenAIRequest } = require('./prompt');
const { validateProviderDecision } = require('./contracts');

const RESPONSES_URL = 'https://api.openai.com/v1/responses';
const MAX_RESPONSE_BYTES = 64 * 1024;

class ProviderError extends Error {
  constructor(code) {
    super(code);
    this.name = 'ProviderError';
    this.code = code;
  }
}

function providerError(code) {
  return new ProviderError(code);
}

function safeTokenCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

async function readBoundedText(body, maxBytes = MAX_RESPONSE_BYTES) {
  if (!body || typeof body.getReader !== 'function') throw providerError('provider_response_invalid');
  const reader = body.getReader();
  const chunks = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = Buffer.from(value);
      total += chunk.length;
      if (total > maxBytes) {
        await reader.cancel();
        throw providerError('provider_response_too_large');
      }
      chunks.push(chunk);
    }
  } finally {
    reader.releaseLock();
  }
  return Buffer.concat(chunks).toString('utf8');
}

function classifyHttpFailure(status, payload) {
  if (status === 401 || status === 403) return providerError('provider_authentication');
  if (status === 429) {
    const code = payload && payload.error && payload.error.code;
    return providerError(code === 'insufficient_quota' ? 'provider_quota' : 'provider_rate_limit');
  }
  if (status >= 500) return providerError('provider_upstream');
  return providerError('provider_request_rejected');
}

function extractOutputText(payload) {
  if (!payload || payload.status !== 'completed') throw providerError('provider_incomplete');
  if (!Array.isArray(payload.output)) throw providerError('provider_output_missing');
  const outputs = [];
  let refused = false;
  for (const item of payload.output) {
    if (!item || !Array.isArray(item.content)) continue;
    for (const content of item.content) {
      if (content && content.type === 'refusal') refused = true;
      if (content && content.type === 'output_text' && typeof content.text === 'string') {
        outputs.push(content.text);
      }
    }
  }
  if (refused) throw providerError('provider_refusal');
  if (outputs.length === 0) throw providerError('provider_output_missing');
  if (outputs.length !== 1) throw providerError('provider_output_invalid');
  return outputs[0];
}

function normalizeUsage(payload) {
  const usage = payload && payload.usage && typeof payload.usage === 'object'
    ? payload.usage
    : {};
  const details = usage.input_tokens_details && typeof usage.input_tokens_details === 'object'
    ? usage.input_tokens_details
    : {};
  return Object.freeze({
    inputTokens: safeTokenCount(usage.input_tokens),
    outputTokens: safeTokenCount(usage.output_tokens),
    cachedTokens: safeTokenCount(details.cached_tokens),
  });
}

class OpenAIProvider {
  #apiKey;

  constructor({
    apiKey = '',
    model = 'gpt-5.6-terra',
    timeoutMs = 8000,
    fetchImpl = globalThis.fetch,
    nowMs = Date.now,
  } = {}) {
    if (typeof apiKey !== 'string') throw new TypeError('apiKey must be a string');
    if (typeof model !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(model)) {
      throw new TypeError('model is invalid');
    }
    if (!Number.isFinite(timeoutMs) || timeoutMs < 1 || timeoutMs > 30_000) {
      throw new TypeError('timeoutMs must be within [1, 30000]');
    }
    if (typeof fetchImpl !== 'function' || typeof nowMs !== 'function') {
      throw new TypeError('fetchImpl and nowMs must be functions');
    }
    this.#apiKey = apiKey;
    this.model = model;
    this.timeoutMs = timeoutMs;
    this.fetchImpl = fetchImpl;
    this.nowMs = nowMs;
    this.providerName = 'openai';
    this.modelId = model;
  }

  async select({ query, evidence, signal }) {
    if (!this.#apiKey) throw providerError('provider_unavailable');
    if (!(signal instanceof AbortSignal)) throw new TypeError('signal must be an AbortSignal');
    if (signal.aborted) throw providerError('request_cancelled');
    const startedAt = this.nowMs();
    const timeoutSignal = AbortSignal.timeout(this.timeoutMs);
    const combinedSignal = AbortSignal.any([signal, timeoutSignal]);
    let response;
    try {
      response = await this.fetchImpl(RESPONSES_URL, {
        method: 'POST',
        signal: combinedSignal,
        headers: {
          Authorization: `Bearer ${this.#apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(buildOpenAIRequest({ query, evidence, model: this.model })),
      });
    } catch (error) {
      if (signal.aborted) throw providerError('request_cancelled');
      if (timeoutSignal.aborted) throw providerError('provider_timeout');
      if (error instanceof ProviderError) throw error;
      throw providerError('provider_network');
    }
    let payload;
    try {
      const body = await readBoundedText(response.body);
      payload = JSON.parse(body);
    } catch (error) {
      if (signal.aborted) throw providerError('request_cancelled');
      if (timeoutSignal.aborted) throw providerError('provider_timeout');
      if (error instanceof ProviderError) throw error;
      throw providerError('provider_response_invalid');
    }
    if (!response.ok) throw classifyHttpFailure(response.status, payload);
    let decision;
    try {
      decision = validateProviderDecision(
        JSON.parse(extractOutputText(payload)),
        new Set(evidence.allowedIdentityIds)
      );
    } catch (error) {
      if (error instanceof ProviderError) throw error;
      throw providerError(error && error.code ? error.code : 'provider_response_invalid');
    }
    const modelId = typeof payload.model === 'string' &&
      /^[A-Za-z0-9._-]{1,128}$/.test(payload.model)
      ? payload.model
      : this.model;
    const latencyMs = this.nowMs() - startedAt;
    if (!Number.isFinite(latencyMs) || latencyMs < 0) {
      throw providerError('provider_clock_invalid');
    }
    return Object.freeze({
      decision,
      provider: 'openai',
      modelId,
      latencyMs,
      usage: normalizeUsage(payload),
    });
  }
}

module.exports = {
  MAX_RESPONSE_BYTES,
  OpenAIProvider,
  ProviderError,
  RESPONSES_URL,
  classifyHttpFailure,
  extractOutputText,
  providerError,
  readBoundedText,
};
