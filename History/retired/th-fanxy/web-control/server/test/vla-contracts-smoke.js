'use strict';

const assert = require('assert/strict');
const { createHash } = require('crypto');
const {
  parseGroundingCommand,
  publicGroundingState,
  validateEvidence,
  validateProviderDecision,
} = require('../vla/contracts');

const JPEG = Buffer.from([0xff, 0xd8, 0x43, 0x4f, 0x4b, 0x45, 0xff, 0xd9]);
const IMAGE_SHA = `sha256:${createHash('sha256').update(JPEG).digest('hex')}`;
const CANDIDATES = [
  { identityId: 12, detectionId: 3, label: 'bottle', identityStatus: 'confirmed', detectionScore: 0.94 },
  { identityId: 15, detectionId: 4, label: 'can', identityStatus: 'confirmed', detectionScore: 0.91 },
];

assert.deepEqual(
  parseGroundingCommand({ cmd: 'ground_language_target', query: '  夹取可乐  ' }),
  { accepted: true, query: '夹取可乐' }
);
for (const invalid of [
  null,
  { cmd: 'ground_language_target', query: '' },
  { cmd: 'ground_language_target', query: 'x'.repeat(257) },
  { cmd: 'ground_language_target', query: '可乐', model: 'attacker-model' },
  { cmd: 'ground_language_target', query: '可乐', identityId: 12 },
]) assert.equal(parseGroundingCommand(invalid).accepted, false);

const evidence = validateEvidence(
  { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000, candidates: CANDIDATES },
  { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
    imageSha256: IMAGE_SHA, jpeg: JPEG },
  1500
);
assert.deepEqual(evidence.allowedIdentityIds, [12, 15]);
assert.deepEqual(evidence.candidates, CANDIDATES);
evidence.jpeg[0] = 0;
assert.equal(JPEG[0], 0xff);

for (const mutation of [
  [
    { frameId: 1843, frameMonotonicNs: 987654321, observedAtMs: 1000, candidates: CANDIDATES },
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      imageSha256: IMAGE_SHA, jpeg: JPEG },
    1500,
  ],
  [
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      candidates: [CANDIDATES[0], { ...CANDIDATES[1], identityId: 12 }] },
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      imageSha256: IMAGE_SHA, jpeg: JPEG },
    1500,
  ],
  [
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000, candidates: CANDIDATES },
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      imageSha256: `sha256:${'0'.repeat(64)}`, jpeg: JPEG },
    1500,
  ],
  [
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000, candidates: CANDIDATES },
    { frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      imageSha256: IMAGE_SHA, jpeg: JPEG },
    3001,
  ],
]) assert.throws(() => validateEvidence(...mutation));

assert.deepEqual(
  validateProviderDecision({
    decision: 'select', identity_id: 12, ambiguous: false,
    explanation: 'ID 12 是可乐瓶。', semantic_score: 0.91,
  }, new Set([12, 15])),
  {
    decision: 'select', identityId: 12, ambiguous: false,
    explanation: 'ID 12 是可乐瓶。', semanticScore: 0.91,
  }
);
assert.deepEqual(
  validateProviderDecision({
    decision: 'clarify', identity_id: null, ambiguous: true,
    explanation: '两个容器都可能符合，请补充包装颜色。', semantic_score: null,
  }, new Set([12, 15])).decision,
  'clarify'
);
assert.deepEqual(
  validateProviderDecision({
    decision: 'none', identity_id: null, ambiguous: false,
    explanation: '画面内没有匹配目标。', semantic_score: null,
  }, new Set([12, 15])).decision,
  'none'
);
for (const invalid of [
  { decision: 'select', identity_id: 99, ambiguous: false, explanation: 'x', semantic_score: 0.9 },
  { decision: 'select', identity_id: 12, ambiguous: true, explanation: 'x', semantic_score: 0.9 },
  { decision: 'clarify', identity_id: 12, ambiguous: true, explanation: 'x', semantic_score: null },
  { decision: 'none', identity_id: null, ambiguous: false, explanation: 'x', semantic_score: null, extra: 1 },
  { decision: 'none', identity_id: null, ambiguous: false, explanation: 'x'.repeat(513), semantic_score: null },
]) assert.throws(() => validateProviderDecision(invalid, new Set([12, 15])));

assert.deepEqual(publicGroundingState({
  status: 'selected', requestId: '11111111-1111-4111-8111-111111111111', identityId: 12,
  explanation: 'ID 12 是可乐瓶。', reason: null, provider: 'mock', modelId: 'mock-v1',
  latencyMs: 3,
}), {
  type: 'grounding_state', status: 'selected',
  requestId: '11111111-1111-4111-8111-111111111111', identityId: 12,
  explanation: 'ID 12 是可乐瓶。', reason: null, provider: 'mock', modelId: 'mock-v1',
  latencyMs: 3,
});
assert.throws(() => publicGroundingState({ status: 'selected', identityId: 12, extra: true }));

console.log('PASS VLA contracts are exact, bounded, provenance-linked, and ID-only');
