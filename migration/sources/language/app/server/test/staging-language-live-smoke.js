'use strict';

const assert = require('assert');
const WebSocket = require('ws');

const endpoint = process.env.STAGING_VOICE_WS || 'ws://127.0.0.1:3002/v1/voice';
const webEndpoint = process.env.STAGING_WEB_WS || 'ws://127.0.0.1:9981/ws';
const timeoutMs = Number(process.env.STAGING_LIVE_TIMEOUT_MS || 120000);

function envelope(type, sessionId, payload) {
  return {
    v: 1,
    type,
    messageId: `live-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    replyTo: null,
    sessionId,
    ts: Date.now(),
    payload,
  };
}

function runPrompt(text) {
  return new Promise((resolve, reject) => {
    const sessionId = `live-language-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const socket = new WebSocket(endpoint, ['thirdhand.voice.v1']);
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
  const message = messages.find(item => item.type === 'intent.candidate');
  if (message) return message.payload;
  const assistant = messages
    .filter(item => item.type === 'assistant.response')
    .map(item => item.payload?.text)
    .filter(Boolean);
  throw new Error(`${label}: no candidate; assistant=${JSON.stringify(assistant)}`);
}

function connectWeb() {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(webEndpoint);
    const messages = [];
    const waiters = [];
    const timer = setTimeout(() => reject(new Error(`web connect timeout: ${webEndpoint}`)), 10000);
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

async function verifyConfirmationGate(candidate) {
  const web = await connectWeb();
  try {
    const config = await web.waitFor(message => message.type === 'config', 'web config');
    assert.equal(config.language.enabled, false);
    web.socket.send(JSON.stringify({ type: 'skill.candidate', candidate }));
    await web.waitFor(
      message => message.type === 'skill.candidate.registered' && message.candidateId === candidate.candidateId,
      'candidate registration'
    );
    web.socket.send(JSON.stringify({
      type: 'confirmation.decision',
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      decision: 'approve',
    }));
    const result = await web.waitFor(
      message => message.type === 'skill.result' && message.candidateId === candidate.candidateId,
      'blocked skill result'
    );
    assert.equal(result.success, false);
    assert.equal(result.status, 'blocked');
    assert.match(result.message, /LANGUAGE_REAL_CONTROL/);
    assert.equal(
      web.messages.some(message => message.type === 'execution.request' && message.candidateId === candidate.candidateId),
      false
    );
  } finally {
    web.socket.close();
  }
}

async function main() {
  const joint = candidateFrom(
    await runPrompt('Increase joint J1 by 1 degree. This action must require confirmation.'),
    'joint step'
  );
  assert.equal(joint.skill, 'manual_joint_control@1');
  assert.equal(joint.intent, 'joint.step');
  assert.deepEqual(joint.payload.params, { action: 'joint.step', joint: 1, deltaDeg: 1 });
  assert.equal(joint.requiresConfirmation, true);

  const gripper = candidateFrom(
    await runPrompt('Open the robot gripper. This action must require confirmation.'),
    'gripper open'
  );
  assert.equal(gripper.skill, 'manual_joint_control@1');
  assert.equal(gripper.intent, 'gripper.open');
  assert.deepEqual(gripper.payload.params, { action: 'gripper.open' });
  assert.equal(gripper.requiresConfirmation, true);

  const coke = candidateFrom(
    await runPrompt('Pick up one Coke bottle and place it in configured drop zone B.'),
    'Coke Skill'
  );
  assert.equal(coke.skill, 'pick_and_place_bottle@1');
  assert.equal(coke.intent, 'pick_and_place_bottle');
  assert.deepEqual(coke.payload.params, {
    object: 'coke_bottle',
    destination: { id: 'drop_zone_b', type: 'configured_drop_zone' },
  });
  assert.equal(coke.requiresConfirmation, true);
  assert.equal('joints' in coke.payload.params, false);
  assert.equal('trajectory' in coke.payload.params, false);

  await verifyConfirmationGate(joint);

  console.log(`PASS live Language tool selection at ${endpoint}`);
  console.log('PASS joint.step, gripper.open, and contract-only Coke Skill candidates');
  console.log(`PASS real candidate -> ${webEndpoint} confirmation gate with no execution.request`);
}

main().catch(error => {
  console.error('FAIL', error);
  process.exitCode = 1;
});
