'use strict';

const assert = require('assert/strict');
const { createHash } = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { GroundingAuditLog } = require('../vla/audit-log');
const { GroundingService } = require('../vla/grounding');
const { MockProvider } = require('../vla/mock-provider');

const REQUEST_ID = '11111111-1111-4111-8111-111111111111';
const JPEG = Buffer.from([0xff, 0xd8, 0x43, 0x4f, 0x4b, 0x45, 0xff, 0xd9]);
const IMAGE_SHA = `sha256:${createHash('sha256').update(JPEG).digest('hex')}`;

function candidate(identityId, detectionId, label) {
  return {
    identityId, detectionId, label, identityStatus: 'confirmed', detectionScore: 0.9,
  };
}

function sourceEvidence() {
  return {
    overlay: {
      frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      imageSha256: IMAGE_SHA, jpeg: JPEG,
    },
    vision: {
      frameId: 1842, frameMonotonicNs: 987654321, observedAtMs: 1000,
      candidates: [candidate(12, 3, 'bottle'), candidate(15, 4, 'can')],
    },
  };
}

function makeAudit() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'vla-grounding-'));
  return {
    directory,
    path: path.join(directory, 'events.jsonl'),
  };
}

(async () => {
  const source = sourceEvidence();
  const audit = makeAudit();
  const events = [];
  const operator = {};
  let currentVision = {
    frameId: 1843, frameMonotonicNs: 987654400, observedAtMs: 1100,
    candidates: [candidate(12, 5, 'bottle')],
  };
  const service = new GroundingService({
    provider: new MockProvider({ identityId: 12, nowMs: () => 1200 }),
    auditLog: new GroundingAuditLog(audit.path, { nowMs: () => 1300 }),
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => currentVision,
    nowMs: () => 1200,
    randomUUID: () => REQUEST_ID,
  });
  await service.submit({ operator, query: '夹取可乐', send: event => events.push(event) });
  assert.deepEqual(events.map(event => event.status), ['analyzing', 'selected']);
  assert.equal(events[1].identityId, 12);
  assert.equal(events[1].explanation, 'Mock provider selected ID 12.');
  assert.equal('position' in events[1], false);
  assert.equal(service.inFlight(operator), false);
  const record = JSON.parse(fs.readFileSync(audit.path, 'utf8').trim());
  assert.equal(record.decision, 'select');
  assert.equal(record.selectedIdentityId, 12);
  assert.deepEqual(record.allowedIdentityIds, [12, 15]);
  assert.equal(record.imageSha256, IMAGE_SHA);
  assert.equal(record.semanticScore, 1);

  currentVision = {
    frameId: 1844, frameMonotonicNs: 987654500, observedAtMs: 1150,
    candidates: [candidate(15, 8, 'can')],
  };
  const rejected = [];
  await service.submit({ operator, query: '夹取可乐', send: event => rejected.push(event) });
  assert.deepEqual(rejected.map(event => event.status), ['analyzing', 'rejected']);
  assert.equal(rejected[1].reason, 'identity_not_current');
  assert.equal(rejected[1].identityId, null);

  currentVision = {
    frameId: 1841, frameMonotonicNs: 900000000, observedAtMs: 900,
    candidates: [candidate(12, 1, 'bottle')],
  };
  const older = [];
  await service.submit({ operator, query: '夹取可乐', send: event => older.push(event) });
  assert.equal(older.at(-1).status, 'rejected');
  assert.equal(older.at(-1).reason, 'current_vision_older_than_source');

  const stale = [];
  const staleService = new GroundingService({
    provider: new MockProvider({ identityId: 12 }),
    auditLog: new GroundingAuditLog(path.join(audit.directory, 'stale.jsonl')),
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => source.vision,
    nowMs: () => 4001,
    randomUUID: () => '22222222-2222-4222-8222-222222222222',
  });
  await staleService.submit({ operator: {}, query: '夹取可乐', send: event => stale.push(event) });
  assert.deepEqual(stale.map(event => event.status), ['analyzing', 'error']);
  assert.equal(stale.at(-1).reason, 'evidence_stale');

  let resolveDeferred;
  const deferredProvider = {
    providerName: 'fake', modelId: 'fake-v1',
    select: ({ signal }) => new Promise((resolve, reject) => {
      resolveDeferred = resolve;
      signal.addEventListener('abort', () => {
        const error = new Error('request_cancelled');
        error.code = 'request_cancelled';
        reject(error);
      }, { once: true });
    }),
  };
  const cancelAudit = makeAudit();
  const cancellationEvents = [];
  const cancellationOperator = {};
  const cancellationService = new GroundingService({
    provider: deferredProvider,
    auditLog: new GroundingAuditLog(cancelAudit.path),
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => currentVision,
    nowMs: () => 1200,
    randomUUID: () => '33333333-3333-4333-8333-333333333333',
  });
  const pending = cancellationService.submit({
    operator: cancellationOperator, query: '夹取可乐',
    send: event => cancellationEvents.push(event),
  });
  await Promise.resolve();
  assert.equal(typeof resolveDeferred, 'function');
  assert.equal(cancellationService.cancel(cancellationOperator, 'browser_disconnected'), true);
  await pending;
  assert.deepEqual(cancellationEvents.map(event => event.status), ['analyzing']);
  const cancelledRecord = JSON.parse(fs.readFileSync(cancelAudit.path, 'utf8').trim());
  assert.equal(cancelledRecord.decision, 'cancelled');
  assert.equal(cancelledRecord.reason, 'browser_disconnected');

  const brokenAudit = {
    appendDecision: () => { throw new Error('disk unavailable'); },
  };
  let brokenCancelCalls = 0;
  const brokenCancelEvents = [];
  const brokenCancelOperator = {};
  const replacementProvider = new MockProvider({ identityId: 12 });
  const brokenCancelService = new GroundingService({
    provider: {
      providerName: 'fake', modelId: 'fake-v1',
      select: args => {
        brokenCancelCalls += 1;
        if (brokenCancelCalls > 1) return replacementProvider.select(args);
        return new Promise((_resolve, reject) => args.signal.addEventListener('abort', () => {
          const error = new Error('request_cancelled');
          error.code = 'request_cancelled';
          reject(error);
        }, { once: true }));
      },
    },
    auditLog: brokenAudit,
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => currentVision,
    nowMs: () => 1200,
    randomUUID: () => '55555555-5555-4555-8555-555555555555',
  });
  const brokenPending = brokenCancelService.submit({
    operator: brokenCancelOperator, query: '第一个请求',
    send: event => brokenCancelEvents.push(event),
  });
  await Promise.resolve();
  await brokenCancelService.submit({
    operator: brokenCancelOperator, query: '替代请求',
    send: event => brokenCancelEvents.push(event),
  });
  await brokenPending;
  assert.equal(brokenCancelCalls, 1);
  assert.deepEqual(brokenCancelEvents.map(event => event.status), ['analyzing', 'error']);
  assert.equal(brokenCancelEvents.at(-1).reason, 'audit_unavailable');
  assert.equal(brokenCancelService.inFlight(brokenCancelOperator), false);

  const auditFailureEvents = [];
  const auditFailureService = new GroundingService({
    provider: new MockProvider({ identityId: 12 }), auditLog: brokenAudit,
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => ({
      frameId: 1843, frameMonotonicNs: 987654400, observedAtMs: 1100,
      candidates: [candidate(12, 5, 'bottle')],
    }),
    nowMs: () => 1200,
    randomUUID: () => '44444444-4444-4444-8444-444444444444',
  });
  await auditFailureService.submit({
    operator: {}, query: '夹取可乐', send: event => auditFailureEvents.push(event),
  });
  assert.equal(auditFailureEvents.at(-1).status, 'error');
  assert.equal(auditFailureEvents.at(-1).reason, 'audit_unavailable');

  fs.rmSync(audit.directory, { recursive: true, force: true });
  fs.rmSync(cancelAudit.directory, { recursive: true, force: true });
  console.log('PASS grounding service revalidates current identity, audits, and cancels per operator');
})().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
