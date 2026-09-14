'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ActiveViewAuditLog } = require('../active-view-audit-log');

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'active-view-audit-'));
const auditPath = path.join(directory, 'events.jsonl');
const evidenceId = `sha256:${'a'.repeat(64)}`;
const first = new ActiveViewAuditLog(auditPath, { nowMs: () => 1000 });
first.append({
  action: 'proposal_rejected',
  sessionId: 'session-1',
  proposalId: 'proposal-1',
  requestId: null,
  evidenceIds: [evidenceId],
  reason: 'proposal_stale',
});
first.append({ action: 'session_cancelled', reason: 'operator_cancelled' });

const restarted = new ActiveViewAuditLog(auditPath, { nowMs: () => 1100 });
restarted.append({ action: 'controller_restarted', reason: null });

const records = fs.readFileSync(auditPath, 'utf8').trim().split('\n').map(JSON.parse);
assert.deepEqual(records.map(record => record.sequence), [1, 2, 3]);
assert.equal(records[0].sessionId, 'session-1');
assert.equal(records[0].proposalId, 'proposal-1');
assert.equal(records[0].requestId, null);
assert.deepEqual(records[0].evidenceIds, [evidenceId]);
assert.equal(records[0].reason, 'proposal_stale');
assert.equal(JSON.stringify(records).includes('NaN'), false);

assert.throws(
  () => restarted.append({ action: 'oversized', reason: 'x'.repeat(70_000) }),
  /64 KiB/
);
assert.throws(
  () => restarted.append({ action: 'nonfinite', value: Number.NaN }),
  /finite JSON/
);
assert.equal(fs.statSync(auditPath).mode & 0o777, 0o600);

fs.rmSync(directory, { recursive: true, force: true });
console.log('PASS active-view audit log is canonical, bounded, and restart-safe');
