'use strict';

const assert = require('assert/strict');
const WebSocket = require('ws');

const voiceEndpoint = process.env.COMPOUND_VOICE_WS || 'ws://127.0.0.1:3003/v1/voice';
const webEndpoint = process.env.COMPOUND_WEB_WS || 'ws://127.0.0.1:9982/ws';
const timeoutMs = Number(process.env.COMPOUND_LIVE_TIMEOUT_MS || 120000);

function envelope(type, sessionId, payload) {
  return {
    v: 1,
    type,
    messageId: `compound-live-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    replyTo: null,
    sessionId,
    ts: Date.now(),
    payload,
  };
}

function runPrompt(text) {
  return new Promise((resolve, reject) => {
    const sessionId = `compound-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const socket = new WebSocket(voiceEndpoint, ['thirdhand.voice.v1']);
    const messages = [];
    const timer = setTimeout(() => {
      socket.terminate();
      reject(new Error(`timeout waiting for Language response: ${text}`));
    }, timeoutMs);
    socket.once('open', () => {
      socket.send(JSON.stringify(envelope('text.submit', sessionId, { text })));
    });
    socket.on('message', raw => {
      const message = JSON.parse(raw.toString());
      messages.push(message);
      if (message.sessionId !== sessionId || message.type !== 'session.completed') return;
      clearTimeout(timer);
      socket.close();
      resolve(messages);
    });
    socket.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function candidateFrom(messages, label) {
  const candidate = messages.find(message => message.type === 'intent.candidate')?.payload;
  if (candidate) return candidate;
  const replies = messages
    .filter(message => message.type === 'assistant.response')
    .map(message => message.payload?.text)
    .filter(Boolean);
  throw new Error(`${label}: no candidate; assistant=${JSON.stringify(replies)}`);
}

function moveMap(candidate) {
  return new Map(candidate.payload.params.moves.map(move => [move.action, move.deltaDeg]));
}

function connectWeb() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webEndpoint);
    const messages = [];
    const waiters = [];
    const timer = setTimeout(() => reject(new Error('web connect timeout')), 10000);
    socket.on('message', raw => {
      const message = JSON.parse(raw.toString());
      messages.push(message);
      for (let index = waiters.length - 1; index >= 0; index -= 1) {
        if (!waiters[index].predicate(message)) continue;
        const waiter = waiters.splice(index, 1)[0];
        clearTimeout(waiter.timer);
        waiter.resolve(message);
      }
    });
    socket.once('open', () => {
      clearTimeout(timer);
      resolve({
        socket,
        messages,
        waitFor(predicate, label) {
          const existing = messages.find(predicate);
          if (existing) return Promise.resolve(existing);
          return new Promise((waitResolve, waitReject) => {
            const waiter = { predicate, resolve: waitResolve, timer: null };
            waiter.timer = setTimeout(() => {
              const index = waiters.indexOf(waiter);
              if (index >= 0) waiters.splice(index, 1);
              waitReject(new Error(`timeout waiting for ${label}`));
            }, timeoutMs);
            waiters.push(waiter);
          });
        },
      });
    });
    socket.once('error', reject);
  });
}

async function registerThenReject(candidate) {
  const web = await connectWeb();
  try {
    const config = await web.waitFor(message => message.type === 'config', '9982 config');
    assert.equal(config.language.directional.realControlEnabled, false);
    web.socket.send(JSON.stringify({ type: 'skill.candidate', candidate }));
    await web.waitFor(
      message => message.type === 'skill.candidate.registered' &&
        message.candidateId === candidate.candidateId,
      'compound candidate registration'
    );
    assert.equal(web.messages.some(message => message.type === 'execution.request'), false);
    web.socket.send(JSON.stringify({
      type: 'confirmation.decision',
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      decision: 'reject',
    }));
    const result = await web.waitFor(
      message => message.type === 'skill.result' && message.candidateId === candidate.candidateId,
      'compound rejection result'
    );
    assert.equal(result.status, 'rejected');
    assert.equal(web.messages.some(message => message.type === 'execution.request'), false);
  } finally {
    web.socket.close();
  }
}

async function assertCompound(text, expected, label) {
  const candidate = candidateFrom(await runPrompt(text), label);
  assert.equal(candidate.skill, 'directional_joint_control@1');
  assert.equal(candidate.intent, 'directional.compound');
  assert.equal(candidate.requiresConfirmation, true);
  assert.equal(candidate.payload.params.moves.length, 2);
  assert.deepEqual(moveMap(candidate), new Map(Object.entries(expected)));
  return candidate;
}

async function main() {
  const chinese = await assertCompound(
    '抬高点，向左点',
    { 'lift.up': 20, 'turn.left': 20 },
    'Chinese defaults'
  );
  await assertCompound(
    'Raise a little and move left a little.',
    { 'lift.up': 20, 'turn.left': 20 },
    'English defaults'
  );
  await assertCompound(
    '抬高并向左 10 度',
    { 'lift.up': 10, 'turn.left': 10 },
    'shared trailing magnitude'
  );
  await registerThenReject(chinese);
  console.log('PASS live Chinese and English compound Directional candidates');
  console.log('PASS default 20 degrees and shared trailing 10 degrees');
  console.log('PASS 9982 registration then rejection with no execution.request');
}

main().catch(error => {
  console.error('FAIL', error);
  process.exitCode = 1;
});
