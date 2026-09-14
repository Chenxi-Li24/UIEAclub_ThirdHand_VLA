'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { GroundingAuditLog } = require('../vla/audit-log');

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'vla-audit-'));
const auditPath = path.join(directory, 'events.jsonl');

function event(overrides = {}) {
  return {
    requestId: '11111111-1111-4111-8111-111111111111',
    query: '夹取可乐',
    provider: 'mock',
    modelId: 'mock-v1',
    promptVersion: 'thirdhand-grounding-v1',
    schemaVersion: 1,
    frameId: 1842,
    frameMonotonicNs: 987654321,
    imageSha256: `sha256:${'a'.repeat(64)}`,
    allowedIdentityIds: [12, 15],
    decision: 'select',
    selectedIdentityId: 12,
    ambiguous: false,
    explanation: 'ID 12 是可乐瓶。',
    semanticScore: 0.91,
    validation: 'accepted',
    reason: null,
    latencyMs: 120,
    usage: { inputTokens: 100, outputTokens: 20, cachedTokens: 0 },
    ...overrides,
  };
}

const first = new GroundingAuditLog(auditPath, { nowMs: () => 1000 });
assert.equal(first.appendDecision(event()).sequence, 1);
assert.equal(first.appendDecision(event({
  requestId: '22222222-2222-4222-8222-222222222222',
  decision: 'none', selectedIdentityId: null, explanation: '没有匹配目标。',
  semanticScore: null, validation: 'not_applicable',
})).sequence, 2);
const restarted = new GroundingAuditLog(auditPath, { nowMs: () => 1100 });
assert.equal(restarted.appendDecision(event({
  requestId: '33333333-3333-4333-8333-333333333333',
})).sequence, 3);

const records = fs.readFileSync(auditPath, 'utf8').trim().split('\n').map(JSON.parse);
assert.deepEqual(records.map(record => record.sequence), [1, 2, 3]);
assert.equal(records[0].imageSha256, `sha256:${'a'.repeat(64)}`);
assert.equal('jpeg' in records[0], false);
assert.equal('apiKey' in records[0], false);
assert.equal(fs.statSync(auditPath).mode & 0o777, 0o600);

for (const injected of [
  { apiKey: 'secret' },
  { authorization: 'Bearer secret' },
  { jpeg: Buffer.from('image') },
  { rawResponse: '{}' },
  { prompt: 'hidden' },
]) assert.throws(() => restarted.appendDecision(event(injected)), /audit_keys_invalid/);
assert.throws(() => restarted.appendDecision(event({ latencyMs: Number.NaN })), /latency/);
assert.throws(() => restarted.appendDecision(event({ explanation: 'x'.repeat(70_000) })), /explanation/);

fs.rmSync(directory, { recursive: true, force: true });
console.log('PASS VLA audit is canonical, bounded, restart-safe, and image/key-free');
