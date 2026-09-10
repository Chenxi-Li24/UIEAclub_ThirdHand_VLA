'use strict';

const { ActiveViewAuditLog } = require('../active-view-audit-log');
const { exactKeys } = require('./contracts');

const AUDIT_KEYS = new Set([
  'requestId', 'query', 'provider', 'modelId', 'promptVersion', 'schemaVersion',
  'frameId', 'frameMonotonicNs', 'imageSha256', 'allowedIdentityIds', 'decision',
  'selectedIdentityId', 'ambiguous', 'explanation', 'semanticScore', 'validation',
  'reason', 'latencyMs', 'usage',
]);
const USAGE_KEYS = new Set(['inputTokens', 'outputTokens', 'cachedTokens']);
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function fail(code) {
  throw new TypeError(code);
}

function boundedText(value, maxCodePoints, name, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string') fail(`${name}_invalid`);
  const text = value.trim();
  const length = Array.from(text).length;
  if (length < 1 || length > maxCodePoints) fail(`${name}_invalid`);
  return text;
}

function optionalInteger(value, name) {
  if (value === null) return null;
  if (!Number.isSafeInteger(value) || value < 0) fail(`${name}_invalid`);
  return value;
}

function optionalFinite(value, name, { maximum = Infinity } = {}) {
  if (value === null) return null;
  if (!Number.isFinite(value) || value < 0 || value > maximum) fail(`${name}_invalid`);
  return value;
}

function validateUsage(value) {
  if (!exactKeys(value, USAGE_KEYS)) fail('usage_keys_invalid');
  return {
    inputTokens: optionalInteger(value.inputTokens, 'input_tokens'),
    outputTokens: optionalInteger(value.outputTokens, 'output_tokens'),
    cachedTokens: optionalInteger(value.cachedTokens, 'cached_tokens'),
  };
}

function validateAuditEvent(event) {
  if (!exactKeys(event, AUDIT_KEYS)) fail('audit_keys_invalid');
  if (!UUID_PATTERN.test(event.requestId)) fail('request_id_invalid');
  const query = boundedText(event.query, 256, 'query');
  const provider = boundedText(event.provider, 128, 'provider');
  const modelId = boundedText(event.modelId, 128, 'model_id');
  const promptVersion = boundedText(event.promptVersion, 128, 'prompt_version');
  if (event.schemaVersion !== 1) fail('schema_version_invalid');
  const frameId = optionalInteger(event.frameId, 'frame_id');
  const frameMonotonicNs = optionalInteger(event.frameMonotonicNs, 'frame_monotonic_ns');
  if ((frameId === null) !== (frameMonotonicNs === null)) fail('frame_provenance_invalid');
  const imageSha256 = event.imageSha256 === null
    ? null
    : boundedText(event.imageSha256, 71, 'image_sha256');
  if (imageSha256 !== null && !/^sha256:[0-9a-f]{64}$/.test(imageSha256)) {
    fail('image_sha256_invalid');
  }
  if ((frameId === null) !== (imageSha256 === null)) fail('image_provenance_invalid');
  if (!Array.isArray(event.allowedIdentityIds) || event.allowedIdentityIds.length > 256 ||
      event.allowedIdentityIds.some(value => !Number.isSafeInteger(value) || value < 0) ||
      new Set(event.allowedIdentityIds).size !== event.allowedIdentityIds.length) {
    fail('allowed_identity_ids_invalid');
  }
  const decisions = new Set(['select', 'clarify', 'none', 'rejected', 'error', 'cancelled']);
  if (!decisions.has(event.decision)) fail('decision_invalid');
  const selectedIdentityId = optionalInteger(event.selectedIdentityId, 'selected_identity_id');
  if (typeof event.ambiguous !== 'boolean') fail('ambiguous_invalid');
  const explanation = boundedText(event.explanation, 512, 'explanation', { nullable: true });
  const semanticScore = optionalFinite(event.semanticScore, 'semantic_score', { maximum: 1 });
  if (!new Set(['accepted', 'rejected', 'not_applicable']).has(event.validation)) {
    fail('validation_invalid');
  }
  const reason = boundedText(event.reason, 128, 'reason', { nullable: true });
  const latencyMs = optionalFinite(event.latencyMs, 'latency');
  if (event.decision === 'select') {
    if (selectedIdentityId === null || !event.allowedIdentityIds.includes(selectedIdentityId) ||
        event.ambiguous || explanation === null || event.validation !== 'accepted' || reason !== null) {
      fail('selected_decision_invalid');
    }
  } else if (selectedIdentityId !== null) {
    fail('non_selection_identity_invalid');
  }
  if (event.decision === 'clarify' && (!event.ambiguous || explanation === null)) {
    fail('clarification_invalid');
  }
  if (new Set(['rejected', 'error', 'cancelled']).has(event.decision) && reason === null) {
    fail('failure_reason_invalid');
  }
  return {
    requestId: event.requestId,
    query,
    provider,
    modelId,
    promptVersion,
    schemaVersion: 1,
    frameId,
    frameMonotonicNs,
    imageSha256,
    allowedIdentityIds: [...event.allowedIdentityIds],
    decision: event.decision,
    selectedIdentityId,
    ambiguous: event.ambiguous,
    explanation,
    semanticScore,
    validation: event.validation,
    reason,
    latencyMs,
    usage: validateUsage(event.usage),
  };
}

class GroundingAuditLog {
  constructor(filePath, options = {}) {
    this.log = new ActiveViewAuditLog(filePath, options);
  }

  appendDecision(event) {
    return this.log.append(validateAuditEvent(event));
  }
}

module.exports = { AUDIT_KEYS, GroundingAuditLog, validateAuditEvent };
