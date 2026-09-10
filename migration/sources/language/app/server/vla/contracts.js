'use strict';

const { createHash } = require('crypto');

const MAX_QUERY_CODE_POINTS = 256;
const MAX_CANDIDATES = 256;
const MAX_JPEG_BYTES = 2 * 1024 * 1024;
const MAX_EXPLANATION_CODE_POINTS = 512;
const PUBLIC_STATE_KEYS = new Set([
  'status', 'requestId', 'identityId', 'explanation', 'reason',
  'provider', 'modelId', 'latencyMs',
]);
const PROVIDER_DECISION_KEYS = new Set([
  'decision', 'identity_id', 'ambiguous', 'explanation', 'semantic_score',
]);

function exactKeys(value, expected) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const required = [...expected].sort();
  return actual.length === required.length &&
    actual.every((key, index) => key === required[index]);
}

function fail(code) {
  const error = new TypeError(code);
  error.code = code;
  throw error;
}

function rejected(reason) {
  return { accepted: false, reason };
}

function boundedText(value, maxCodePoints) {
  if (typeof value !== 'string') return null;
  const normalized = value.trim();
  const length = Array.from(normalized).length;
  return length >= 1 && length <= maxCodePoints ? normalized : null;
}

function nonNegativeSafeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function parseGroundingCommand(message) {
  if (!exactKeys(message, new Set(['cmd', 'query'])) ||
      message.cmd !== 'ground_language_target') {
    return rejected('browser_command_keys_invalid');
  }
  const query = boundedText(message.query, MAX_QUERY_CODE_POINTS);
  if (query === null) return rejected('query_length_invalid');
  return { accepted: true, query };
}

function validateCandidate(value) {
  const keys = new Set([
    'identityId', 'detectionId', 'label', 'identityStatus', 'detectionScore',
  ]);
  if (!exactKeys(value, keys)) fail('candidate_keys_invalid');
  if (!nonNegativeSafeInteger(value.identityId)) fail('candidate_identity_invalid');
  if (!nonNegativeSafeInteger(value.detectionId)) fail('candidate_detection_invalid');
  const label = boundedText(value.label, 128);
  if (label === null) fail('candidate_label_invalid');
  if (value.identityStatus !== 'confirmed') fail('candidate_identity_not_confirmed');
  if (!Number.isFinite(value.detectionScore) ||
      value.detectionScore < 0 || value.detectionScore > 1) {
    fail('candidate_score_invalid');
  }
  return Object.freeze({
    identityId: value.identityId,
    detectionId: value.detectionId,
    label,
    identityStatus: 'confirmed',
    detectionScore: value.detectionScore,
  });
}

function validateEvidence(vision, overlay, nowMs, { maxAgeMs = 2000 } = {}) {
  const visionKeys = new Set([
    'frameId', 'frameMonotonicNs', 'observedAtMs', 'candidates',
  ]);
  const overlayKeys = new Set([
    'frameId', 'frameMonotonicNs', 'observedAtMs', 'imageSha256', 'jpeg',
  ]);
  if (!exactKeys(vision, visionKeys) || !exactKeys(overlay, overlayKeys)) {
    fail('evidence_keys_invalid');
  }
  if (!Number.isFinite(nowMs) || !Number.isFinite(maxAgeMs) || maxAgeMs <= 0) {
    fail('evidence_time_invalid');
  }
  for (const value of [vision.frameId, vision.frameMonotonicNs, overlay.frameId,
    overlay.frameMonotonicNs]) {
    if (!nonNegativeSafeInteger(value)) fail('evidence_provenance_invalid');
  }
  if (!Number.isFinite(vision.observedAtMs) || vision.observedAtMs < 0 ||
      !Number.isFinite(overlay.observedAtMs) || overlay.observedAtMs < 0) {
    fail('evidence_timestamp_invalid');
  }
  if (vision.frameId !== overlay.frameId ||
      vision.frameMonotonicNs !== overlay.frameMonotonicNs ||
      vision.observedAtMs !== overlay.observedAtMs) {
    fail('evidence_provenance_mismatch');
  }
  const ageMs = nowMs - vision.observedAtMs;
  if (ageMs < 0 || ageMs > maxAgeMs) fail('evidence_stale');
  if (!Buffer.isBuffer(overlay.jpeg) || overlay.jpeg.length < 4 ||
      overlay.jpeg.length > MAX_JPEG_BYTES || overlay.jpeg[0] !== 0xff ||
      overlay.jpeg[1] !== 0xd8 || overlay.jpeg.at(-2) !== 0xff ||
      overlay.jpeg.at(-1) !== 0xd9) {
    fail('evidence_jpeg_invalid');
  }
  if (!/^sha256:[0-9a-f]{64}$/.test(overlay.imageSha256)) {
    fail('evidence_hash_invalid');
  }
  const computed = `sha256:${createHash('sha256').update(overlay.jpeg).digest('hex')}`;
  if (computed !== overlay.imageSha256) fail('evidence_hash_mismatch');
  if (!Array.isArray(vision.candidates) || vision.candidates.length < 1 ||
      vision.candidates.length > MAX_CANDIDATES) {
    fail('candidate_count_invalid');
  }
  const candidates = vision.candidates.map(validateCandidate);
  const identities = candidates.map(candidate => candidate.identityId);
  const detections = candidates.map(candidate => candidate.detectionId);
  if (new Set(identities).size !== identities.length) fail('candidate_identity_duplicated');
  if (new Set(detections).size !== detections.length) fail('candidate_detection_duplicated');
  return Object.freeze({
    frameId: vision.frameId,
    frameMonotonicNs: vision.frameMonotonicNs,
    observedAtMs: vision.observedAtMs,
    imageSha256: overlay.imageSha256,
    jpeg: Buffer.from(overlay.jpeg),
    candidates: Object.freeze(candidates),
    allowedIdentityIds: Object.freeze(identities),
  });
}

function validateProviderDecision(value, allowedIds) {
  if (!(allowedIds instanceof Set) ||
      [...allowedIds].some(identityId => !nonNegativeSafeInteger(identityId))) {
    fail('allowed_identity_ids_invalid');
  }
  if (!exactKeys(value, PROVIDER_DECISION_KEYS)) fail('provider_decision_keys_invalid');
  if (!new Set(['select', 'clarify', 'none']).has(value.decision)) {
    fail('provider_decision_invalid');
  }
  const explanation = boundedText(value.explanation, MAX_EXPLANATION_CODE_POINTS);
  if (explanation === null) fail('provider_explanation_invalid');
  let semanticScore = value.semantic_score;
  if (semanticScore !== null) {
    if (!Number.isFinite(semanticScore) || semanticScore < 0 || semanticScore > 1) {
      fail('provider_semantic_score_invalid');
    }
    semanticScore = Number(semanticScore);
  }
  if (value.decision === 'select') {
    if (!nonNegativeSafeInteger(value.identity_id) || !allowedIds.has(value.identity_id)) {
      fail('identity_not_allowed');
    }
    if (value.ambiguous !== false) fail('selected_identity_ambiguous');
  } else {
    if (value.identity_id !== null) fail('non_selection_identity_must_be_null');
    if (value.decision === 'clarify' && value.ambiguous !== true) {
      fail('clarification_must_be_ambiguous');
    }
    if (value.decision === 'none' && value.ambiguous !== false) {
      fail('none_must_not_be_ambiguous');
    }
  }
  return Object.freeze({
    decision: value.decision,
    identityId: value.identity_id,
    ambiguous: value.ambiguous,
    explanation,
    semanticScore,
  });
}

function nullableBoundedText(value, maxCodePoints, code) {
  if (value === null) return null;
  const text = boundedText(value, maxCodePoints);
  if (text === null) fail(code);
  return text;
}

function publicGroundingState(value) {
  if (!exactKeys(value, PUBLIC_STATE_KEYS)) fail('public_state_keys_invalid');
  const statuses = new Set(['analyzing', 'selected', 'clarify', 'none', 'rejected', 'error']);
  if (!statuses.has(value.status)) fail('public_state_status_invalid');
  const requestId = nullableBoundedText(value.requestId, 64, 'public_request_id_invalid');
  const explanation = nullableBoundedText(
    value.explanation, MAX_EXPLANATION_CODE_POINTS, 'public_explanation_invalid'
  );
  const reason = nullableBoundedText(value.reason, 128, 'public_reason_invalid');
  const provider = nullableBoundedText(value.provider, 128, 'public_provider_invalid');
  const modelId = nullableBoundedText(value.modelId, 128, 'public_model_invalid');
  if (value.latencyMs !== null && (!Number.isFinite(value.latencyMs) || value.latencyMs < 0)) {
    fail('public_latency_invalid');
  }
  if (value.status === 'selected') {
    if (!nonNegativeSafeInteger(value.identityId) || explanation === null || reason !== null) {
      fail('public_selected_state_invalid');
    }
  } else if (value.identityId !== null) {
    fail('public_non_selection_identity_invalid');
  }
  if (new Set(['clarify', 'none']).has(value.status) && explanation === null) {
    fail('public_non_selection_explanation_invalid');
  }
  if (new Set(['rejected', 'error']).has(value.status) && reason === null) {
    fail('public_failure_reason_invalid');
  }
  return Object.freeze({
    type: 'grounding_state',
    status: value.status,
    requestId,
    identityId: value.identityId,
    explanation,
    reason,
    provider,
    modelId,
    latencyMs: value.latencyMs,
  });
}

module.exports = {
  MAX_CANDIDATES,
  MAX_EXPLANATION_CODE_POINTS,
  MAX_JPEG_BYTES,
  MAX_QUERY_CODE_POINTS,
  exactKeys,
  parseGroundingCommand,
  publicGroundingState,
  validateEvidence,
  validateProviderDecision,
};
