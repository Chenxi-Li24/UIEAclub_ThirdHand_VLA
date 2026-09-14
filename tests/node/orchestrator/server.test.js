'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { WebSocket } = require('ws');
const { createOrchestrator } = require('../../../apps/orchestrator/src/server');

function nextMessage(socket, predicate, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('message timeout')), timeoutMs);
    const handler = data => {
      const message = JSON.parse(data.toString('utf8'));
      if (!predicate(message)) return;
      clearTimeout(timer);
      socket.off('message', handler);
      resolve(message);
    };
    socket.on('message', handler);
  });
}

function ready(now = Date.now()) {
  return {
    robot: { reachable: true, connected: true, stateReady: true, moving: false, fresh: true },
    skill: { id: 'manipulation.gripper-control', available: true },
    authorizationReady: true,
    capturedAt: new Date(now).toISOString(),
  };
}

test('candidate cannot execute before one exact authorization', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-orchestrator-'));
  const calls = [];
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    readinessProvider: async () => ready(),
    robotClient: { execute: async primitive => { calls.push(primitive); return { status: 'completed', code: 'target_reached', actualPercent: 100, maxJointDeltaDeg: 0 }; }, close() {} },
  });
  t.after(async () => {
    await orchestrator.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await orchestrator.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  t.after(() => socket.close());

  socket.send(JSON.stringify({
    type: 'candidate.submit',
    candidate: { candidateId: 'candidate-1', traceId: 'trace-1', intent: 'gripper.open', source: 'voice', transcript: '打开夹爪' },
  }));
  const proposed = await nextMessage(socket, message => message.type === 'plan.proposed');
  assert.equal(calls.length, 0);
  assert.equal(proposed.proposal.plan.steps[0].parameters.positionPercent, 100);

  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  }));
  const result = await nextMessage(socket, message => message.type === 'skill.result');
  assert.equal(result.result.status, 'completed');
  assert.equal(calls.length, 1);

  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  }));
  const rejected = await nextMessage(socket, message => message.type === 'plan.rejected');
  assert.equal(rejected.code, 'authorization_replayed');
  assert.equal(calls.length, 1);
});

test('unsupported candidates and mutated digests fail closed', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-orchestrator-'));
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    readinessProvider: async () => ready(),
    robotClient: { execute: async () => { throw new Error('must not execute'); }, close() {} },
  });
  t.after(async () => { await orchestrator.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await orchestrator.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  t.after(() => socket.close());

  socket.send(JSON.stringify({ type: 'candidate.submit', candidate: { candidateId: 'c0', traceId: 't0', intent: 'arm.home', source: 'voice', transcript: '回零' } }));
  assert.equal((await nextMessage(socket, message => message.type === 'plan.rejected')).code, 'unsupported_intent');

  socket.send(JSON.stringify({ type: 'candidate.submit', candidate: { candidateId: 'c1', traceId: 't1', intent: 'gripper.close', source: 'text', transcript: '关闭夹爪' } }));
  const proposed = await nextMessage(socket, message => message.type === 'plan.proposed');
  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: 1,
    planDigest: `sha256:${'0'.repeat(64)}`,
  }));
  assert.equal((await nextMessage(socket, message => message.type === 'plan.rejected')).code, 'plan_digest_mismatch');
});

test('a cancelled proposal cannot be authorized later', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-orchestrator-'));
  const calls = [];
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    readinessProvider: async () => ready(),
    robotClient: { execute: async primitive => { calls.push(primitive); return { status: 'completed' }; }, close() {} },
  });
  t.after(async () => { await orchestrator.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await orchestrator.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  t.after(() => socket.close());

  socket.send(JSON.stringify({ type: 'candidate.submit', candidate: { candidateId: 'cancel-1', traceId: 'trace-cancel', intent: 'gripper.open', source: 'voice', transcript: '打开夹爪' } }));
  const proposed = await nextMessage(socket, message => message.type === 'plan.proposed');
  socket.send(JSON.stringify({ type: 'proposal.cancel', proposalId: proposed.proposal.proposalId, reason: 'user_rejected' }));
  assert.equal((await nextMessage(socket, message => message.type === 'proposal.cancelled')).proposalId, proposed.proposal.proposalId);

  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  }));
  assert.equal((await nextMessage(socket, message => message.type === 'plan.rejected')).code, 'proposal_unknown');
  assert.equal(calls.length, 0);
});

test('browser disconnect during execution aborts Robot wait and interrupts the task', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-orchestrator-'));
  let aborted = false;
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    readinessProvider: async () => ready(),
    robotClient: {
      execute: async (_, { signal } = {}) => new Promise((resolve, reject) => {
        signal?.addEventListener('abort', () => {
          aborted = true;
          reject(Object.assign(new Error('execution interrupted'), { code: 'interrupted' }));
        }, { once: true });
      }),
      close() {},
    },
  });
  t.after(async () => { await orchestrator.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await orchestrator.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });

  socket.send(JSON.stringify({ type: 'candidate.submit', candidate: { candidateId: 'disconnect-1', traceId: 'trace-disconnect', intent: 'gripper.close', source: 'voice', transcript: '关闭夹爪' } }));
  const proposed = await nextMessage(socket, message => message.type === 'plan.proposed');
  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  }));
  await nextMessage(socket, message => message.type === 'execution.started');
  const replay = nextMessage(socket, message => message.type === 'plan.rejected');
  socket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  }));
  assert.equal((await replay).code, 'authorization_replayed');
  socket.close();
  await new Promise(resolve => setTimeout(resolve, 50));

  assert.equal(aborted, true);
  assert.equal(orchestrator.engine.getTask(proposed.proposal.plan.taskId).state, 'interrupted');
});

test('client messages with additional fields fail closed', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-orchestrator-'));
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    readinessProvider: async () => ready(),
    robotClient: { execute: async () => { throw new Error('must not execute'); }, close() {} },
  });
  t.after(async () => { await orchestrator.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await orchestrator.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/plan`, 'thirdhand.plan.v1');
  await new Promise((resolve, reject) => { socket.once('open', resolve); socket.once('error', reject); });
  t.after(() => socket.close());

  socket.send(JSON.stringify({
    type: 'candidate.submit',
    candidate: { ...ready(), candidateId: 'extra-1', traceId: 'trace-extra', intent: 'gripper.open', source: 'voice', transcript: '打开夹爪', extra: true },
  }));
  assert.equal((await nextMessage(socket, message => message.type === 'plan.rejected')).code, 'message_invalid');
});
