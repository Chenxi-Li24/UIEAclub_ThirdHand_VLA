import test from 'node:test';
import assert from 'node:assert/strict';

import { PlanChannel } from '../../../apps/web/public/js/plan-channel.mjs';

class FakeWsClient {
  constructor() {
    this.connected = true;
    this.listeners = new Map();
    this.sent = [];
  }

  on(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type, message) {
    for (const listener of this.listeners.get(type) || []) listener(message);
  }

  send(message) {
    if (!this.connected) return false;
    this.sent.push(message);
    return true;
  }
}

function speechCandidate() {
  return {
    candidateId: 'candidate-1',
    traceId: 'trace-1',
    intent: 'gripper.open',
    sourceText: '打开夹爪',
    payload: { params: { action: 'open' } },
    requiresConfirmation: true,
  };
}

function proposal() {
  return {
    proposalId: 'proposal-1',
    candidateId: 'candidate-1',
    planDigest: `sha256:${'a'.repeat(64)}`,
    plan: { planId: 'plan-1', revision: 1 },
  };
}

test('PlanChannel normalizes Speech candidates and grants the exact displayed plan once', () => {
  const ws = new FakeWsClient();
  const channel = new PlanChannel(ws);
  const observed = [];
  channel.on('plan.proposed', message => observed.push(message));

  assert.equal(channel.submitCandidate(speechCandidate(), 'voice'), true);
  assert.deepEqual(ws.sent[0], {
    type: 'candidate.submit',
    candidate: {
      candidateId: 'candidate-1',
      traceId: 'trace-1',
      intent: 'gripper.open',
      source: 'voice',
      transcript: '打开夹爪',
    },
  });
  ws.emit('message', { type: 'plan.proposed', proposal: proposal() });
  assert.equal(observed.length, 1);
  assert.equal(channel.canConfirm(), true);
  assert.equal(channel.grantAuthorization(proposal()), true);
  assert.deepEqual(ws.sent[1], {
    type: 'authorization.grant',
    proposalId: 'proposal-1',
    planId: 'plan-1',
    planRevision: 1,
    planDigest: `sha256:${'a'.repeat(64)}`,
  });
  assert.equal(channel.grantAuthorization(proposal()), false);
});

test('PlanChannel cancellation invalidates a proposal and disconnect clears all state', () => {
  const ws = new FakeWsClient();
  const channel = new PlanChannel(ws);
  channel.submitCandidate(speechCandidate(), 'text');
  ws.emit('message', { type: 'plan.proposed', proposal: proposal() });
  assert.equal(channel.cancelProposal('user_rejected'), true);
  assert.deepEqual(ws.sent[1], {
    type: 'proposal.cancel',
    proposalId: 'proposal-1',
    reason: 'user_rejected',
  });
  assert.equal(channel.canConfirm(), false);

  ws.emit('ws_connection', { connected: false });
  assert.equal(channel.isReady(), false);
  assert.equal(channel.grantAuthorization(proposal()), false);
});

test('PlanChannel surfaces unknown server messages without changing authorization state', () => {
  const ws = new FakeWsClient();
  const channel = new PlanChannel(ws);
  const errors = [];
  channel.on('channel.error', message => errors.push(message));
  channel.submitCandidate(speechCandidate(), 'voice');
  ws.emit('message', { type: 'future.execute', payload: { unsafe: true } });

  assert.equal(errors[0].code, 'unsupported_server_message');
  assert.equal(channel.canConfirm(), false);
  assert.equal(ws.sent.length, 1);
});

test('PlanChannel rejects malformed proposals without enabling confirmation', () => {
  const ws = new FakeWsClient();
  const channel = new PlanChannel(ws);
  const errors = [];
  channel.on('channel.error', message => errors.push(message));
  channel.submitCandidate(speechCandidate(), 'voice');
  ws.emit('message', {
    type: 'plan.proposed',
    proposal: { proposalId: 'proposal-1', candidateId: 'candidate-1', plan: {} },
  });

  assert.equal(errors[0].code, 'malformed_server_message');
  assert.equal(channel.canConfirm(), false);
});
