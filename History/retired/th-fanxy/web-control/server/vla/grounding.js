'use strict';

const { PROMPT_VERSION } = require('./prompt');
const { publicGroundingState, validateEvidence } = require('./contracts');

function safeReason(error, fallback = 'grounding_failed') {
  const value = error && (error.code || error.message);
  return typeof value === 'string' && /^[a-z0-9_.-]{1,128}$/.test(value)
    ? value
    : fallback;
}

function providerMetadata(provider) {
  let providerName = provider.providerName;
  if (typeof providerName !== 'string') {
    providerName = provider.constructor && provider.constructor.name === 'MockProvider'
      ? 'mock'
      : 'openai';
  }
  let modelId = provider.modelId;
  if (typeof modelId !== 'string') modelId = provider.model || `${providerName}-unknown`;
  return { providerName, modelId };
}

function emptyUsage() {
  return { inputTokens: null, outputTokens: null, cachedTokens: null };
}

class GroundingService {
  constructor({
    provider,
    auditLog,
    getOverlaySnapshot,
    getVisionSnapshot,
    getCurrentVisionSnapshot = getVisionSnapshot,
    nowMs = Date.now,
    randomUUID = require('crypto').randomUUID,
    maxAgeMs = 2000,
  }) {
    if (!provider || typeof provider.select !== 'function') {
      throw new TypeError('provider.select is required');
    }
    if (!auditLog || typeof auditLog.appendDecision !== 'function') {
      throw new TypeError('auditLog.appendDecision is required');
    }
    for (const [name, value] of Object.entries({
      getOverlaySnapshot, getVisionSnapshot, getCurrentVisionSnapshot, nowMs, randomUUID,
    })) {
      if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    }
    if (!Number.isFinite(maxAgeMs) || maxAgeMs <= 0) {
      throw new TypeError('maxAgeMs must be finite and positive');
    }
    this.provider = provider;
    this.auditLog = auditLog;
    this.getOverlaySnapshot = getOverlaySnapshot;
    this.getVisionSnapshot = getVisionSnapshot;
    this.getCurrentVisionSnapshot = getCurrentVisionSnapshot;
    this.nowMs = nowMs;
    this.randomUUID = randomUUID;
    this.maxAgeMs = maxAgeMs;
    this.jobs = new Map();
    const metadata = providerMetadata(provider);
    this.providerName = metadata.providerName;
    this.modelId = metadata.modelId;
  }

  inFlight(operator) {
    return this.jobs.has(operator);
  }

  _public(status, job, values = {}) {
    return publicGroundingState({
      status,
      requestId: job.requestId,
      identityId: values.identityId ?? null,
      explanation: values.explanation ?? null,
      reason: values.reason ?? null,
      provider: values.provider || this.providerName,
      modelId: values.modelId || this.modelId,
      latencyMs: values.latencyMs ?? null,
    });
  }

  _auditEvent(job, values) {
    const evidence = job.evidence;
    return {
      requestId: job.requestId,
      query: job.query,
      provider: values.provider || this.providerName,
      modelId: values.modelId || this.modelId,
      promptVersion: PROMPT_VERSION,
      schemaVersion: 1,
      frameId: evidence ? evidence.frameId : null,
      frameMonotonicNs: evidence ? evidence.frameMonotonicNs : null,
      imageSha256: evidence ? evidence.imageSha256 : null,
      allowedIdentityIds: evidence ? [...evidence.allowedIdentityIds] : [],
      decision: values.decision,
      selectedIdentityId: values.selectedIdentityId ?? null,
      ambiguous: values.ambiguous === true,
      explanation: values.explanation ?? null,
      semanticScore: values.semanticScore ?? null,
      validation: values.validation,
      reason: values.reason ?? null,
      latencyMs: values.latencyMs ?? Math.max(0, this.nowMs() - job.startedAtMs),
      usage: values.usage || emptyUsage(),
    };
  }

  _appendAudit(job, values) {
    try {
      this.auditLog.appendDecision(this._auditEvent(job, values));
      return true;
    } catch (_) {
      return false;
    }
  }

  _currentSelection(identityId, evidence) {
    const current = this.getCurrentVisionSnapshot();
    if (!current || typeof current !== 'object') {
      return { accepted: false, reason: 'current_vision_unavailable' };
    }
    if (!Number.isSafeInteger(current.frameMonotonicNs) ||
        current.frameMonotonicNs < evidence.frameMonotonicNs ||
        !Number.isFinite(current.observedAtMs) || current.observedAtMs < evidence.observedAtMs) {
      return { accepted: false, reason: 'current_vision_older_than_source' };
    }
    const ageMs = this.nowMs() - current.observedAtMs;
    if (ageMs < 0 || ageMs > this.maxAgeMs) {
      return { accepted: false, reason: 'current_vision_stale' };
    }
    if (!Array.isArray(current.candidates) || !current.candidates.some(candidate =>
      candidate && candidate.identityId === identityId &&
      candidate.identityStatus === 'confirmed')) {
      return { accepted: false, reason: 'identity_not_current' };
    }
    return { accepted: true };
  }

  _auditFailureState(job, reason) {
    return this._public('error', job, { reason: reason || 'audit_unavailable' });
  }

  cancel(operator, reason = 'request_cancelled') {
    const job = this.jobs.get(operator);
    if (!job) return false;
    this.jobs.delete(operator);
    job.controller.abort();
    return this._appendAudit(job, {
      decision: 'cancelled',
      validation: 'not_applicable',
      reason: safeReason({ code: reason }, 'request_cancelled'),
      usage: emptyUsage(),
    });
  }

  async submit({ operator, query, send }) {
    if ((typeof operator !== 'object' && typeof operator !== 'function') || operator === null) {
      throw new TypeError('operator must be an object');
    }
    if (typeof send !== 'function') throw new TypeError('send must be a function');
    if (typeof query !== 'string' || Array.from(query.trim()).length < 1 ||
        Array.from(query.trim()).length > 256) {
      throw new TypeError('query must contain 1 to 256 code points');
    }
    const existing = this.jobs.get(operator);
    if (existing && !this.cancel(operator, 'superseded')) {
      send(this._auditFailureState(existing, 'audit_unavailable'));
      return;
    }
    const job = {
      requestId: this.randomUUID(),
      query: query.trim(),
      controller: new AbortController(),
      evidence: null,
      startedAtMs: this.nowMs(),
    };
    this.jobs.set(operator, job);
    send(this._public('analyzing', job));
    try {
      job.evidence = validateEvidence(
        this.getVisionSnapshot(),
        this.getOverlaySnapshot(),
        this.nowMs(),
        { maxAgeMs: this.maxAgeMs }
      );
      const result = await this.provider.select({
        query: job.query,
        evidence: job.evidence,
        signal: job.controller.signal,
      });
      if (this.jobs.get(operator) !== job) return;
      const common = {
        provider: result.provider,
        modelId: result.modelId,
        latencyMs: result.latencyMs,
        usage: result.usage,
        explanation: result.decision.explanation,
        semanticScore: result.decision.semanticScore,
        ambiguous: result.decision.ambiguous,
      };
      if (result.decision.decision === 'select') {
        const revalidation = this._currentSelection(result.decision.identityId, job.evidence);
        if (!revalidation.accepted) {
          const auditValues = {
            ...common,
            decision: 'rejected',
            selectedIdentityId: null,
            validation: 'rejected',
            reason: revalidation.reason,
          };
          if (!this._appendAudit(job, auditValues)) {
            send(this._auditFailureState(job, 'audit_unavailable'));
            return;
          }
          send(this._public('rejected', job, { ...common, reason: revalidation.reason }));
          return;
        }
        const auditValues = {
          ...common,
          decision: 'select',
          selectedIdentityId: result.decision.identityId,
          validation: 'accepted',
          reason: null,
        };
        if (!this._appendAudit(job, auditValues)) {
          send(this._auditFailureState(job, 'audit_unavailable'));
          return;
        }
        send(this._public('selected', job, {
          ...common,
          identityId: result.decision.identityId,
          reason: null,
        }));
        return;
      }
      const decision = result.decision.decision;
      const auditValues = {
        ...common,
        decision,
        selectedIdentityId: null,
        validation: 'not_applicable',
        reason: null,
      };
      if (!this._appendAudit(job, auditValues)) {
        send(this._auditFailureState(job, 'audit_unavailable'));
        return;
      }
      send(this._public(decision, job, { ...common, identityId: null, reason: null }));
    } catch (error) {
      if (this.jobs.get(operator) !== job) return;
      const reason = safeReason(error);
      if (!this._appendAudit(job, {
        decision: 'error',
        validation: 'rejected',
        reason,
        usage: emptyUsage(),
      })) {
        send(this._auditFailureState(job, 'audit_unavailable'));
        return;
      }
      send(this._public('error', job, { reason }));
    } finally {
      if (this.jobs.get(operator) === job) this.jobs.delete(operator);
    }
  }
}

module.exports = { GroundingService, providerMetadata, safeReason };
