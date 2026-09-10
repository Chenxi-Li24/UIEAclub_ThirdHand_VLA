'use strict';

const { validateProviderDecision } = require('./contracts');

function mockError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

class MockProvider {
  constructor({ identityId = null, selector = null, nowMs = Date.now } = {}) {
    if (identityId !== null && (!Number.isSafeInteger(identityId) || identityId < 0)) {
      throw new TypeError('identityId must be a non-negative integer or null');
    }
    if (selector !== null && typeof selector !== 'function') {
      throw new TypeError('selector must be a function or null');
    }
    if (typeof nowMs !== 'function') throw new TypeError('nowMs must be a function');
    this.identityId = identityId;
    this.selector = selector;
    this.nowMs = nowMs;
    this.providerName = 'mock';
    this.modelId = 'mock-v1';
  }

  async select({ query, evidence, signal }) {
    if (!(signal instanceof AbortSignal)) throw new TypeError('signal must be an AbortSignal');
    if (signal.aborted) throw mockError('request_cancelled');
    const startedAt = this.nowMs();
    const identityId = this.selector
      ? this.selector({ query, candidates: evidence.candidates })
      : this.identityId;
    const raw = identityId === null
      ? {
        decision: 'none',
        identity_id: null,
        ambiguous: false,
        explanation: 'Mock provider found no configured match.',
        semantic_score: null,
      }
      : {
        decision: 'select',
        identity_id: identityId,
        ambiguous: false,
        explanation: `Mock provider selected ID ${identityId}.`,
        semantic_score: 1,
      };
    const decision = validateProviderDecision(raw, new Set(evidence.allowedIdentityIds));
    const latencyMs = this.nowMs() - startedAt;
    if (!Number.isFinite(latencyMs) || latencyMs < 0) throw mockError('provider_clock_invalid');
    return Object.freeze({
      decision,
      provider: 'mock',
      modelId: 'mock-v1',
      latencyMs,
      usage: Object.freeze({ inputTokens: 0, outputTokens: 0, cachedTokens: 0 }),
    });
  }
}

module.exports = { MockProvider };
