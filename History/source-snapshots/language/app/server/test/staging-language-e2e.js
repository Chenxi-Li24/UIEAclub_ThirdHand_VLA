'use strict';

const assert = require('assert');
const WebSocket = require('ws');

const webEndpoint = process.env.STAGING_WEB_WS || 'ws://127.0.0.1:3100/ws';
const voiceEndpoint = process.env.STAGING_VOICE_WS || 'ws://192.168.58.68:3002/v1/voice';
const timeoutMs = Number(process.env.STAGING_E2E_TIMEOUT_MS || 90000);
let webSocket;
let voiceSocket;

function connect(url, protocols) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, protocols);
    const messageInbox = inbox(socket);
    const timer = setTimeout(() => reject(new Error(`connect timeout: ${url}`)), 10000);
    socket.once('open', () => { clearTimeout(timer); resolve({ socket, messageInbox }); });
    socket.once('error', error => { clearTimeout(timer); reject(error); });
  });
}

function inbox(socket) {
  const messages = [];
  const waiters = [];
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
  return {
    messages,
    waitFor(predicate, label) {
      const existing = messages.find(predicate);
      if (existing) return Promise.resolve(existing);
      return new Promise((resolve, reject) => {
        const waiter = { predicate, resolve, timer: null };
        waiter.timer = setTimeout(() => {
          const index = waiters.indexOf(waiter);
          if (index >= 0) waiters.splice(index, 1);
          reject(new Error(`timeout waiting for ${label}`));
        }, timeoutMs);
        waiters.push(waiter);
      });
    },
  };
}

function envelope(type, sessionId, payload) {
  return {
    v: 1,
    type,
    messageId: `stage-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    replyTo: null,
    sessionId,
    ts: Date.now(),
    payload,
  };
}

async function main() {
  const runtimeConfigUrl = new URL(webEndpoint);
  runtimeConfigUrl.protocol = runtimeConfigUrl.protocol === 'wss:' ? 'https:' : 'http:';
  runtimeConfigUrl.pathname = '/api/runtime-config';
  const runtimeResponse = await fetch(runtimeConfigUrl);
  assert.equal(runtimeResponse.status, 200);
  const runtimeConfig = await runtimeResponse.json();
  assert.equal(runtimeConfig.language?.voiceEndpoint, voiceEndpoint);

  const webConnection = await connect(webEndpoint);
  const web = webConnection.socket;
  webSocket = web;
  const webInbox = webConnection.messageInbox;
  const config = await webInbox.waitFor(message => message.type === 'config', 'web config');
  assert.equal(config.language.enabled, false);
  assert.equal(config.language.skill, 'manual_joint_control@1');
  web.send(JSON.stringify({ cmd: 'connect' }));
  await webInbox.waitFor(message => message.type === 'robot_state' && message.stateName === 'IDLE', 'simulator IDLE state');

  let candidate;
  if (process.env.STAGING_SKIP_VOICE === '1') {
    const now = Date.now();
    candidate = {
      candidateId: `stage-candidate-${now}`,
      traceId: `stage-trace-${now}`,
      sourceText: 'J1 增加 1 度',
      skill: 'manual_joint_control@1',
      createdAt: now,
      expiresAt: now + 120000,
      requiresConfirmation: true,
      intent: 'joint.step',
      payload: { params: { action: 'joint.step', joint: 1, deltaDeg: 1 } },
    };
  } else {
    const voiceConnection = await connect(voiceEndpoint, ['thirdhand.voice.v1']);
    const voice = voiceConnection.socket;
    voiceSocket = voice;
    const voiceInbox = voiceConnection.messageInbox;
    const sessionId = `stage-language-${Date.now()}`;
    voice.send(JSON.stringify(envelope('text.submit', sessionId, {
      text: '请把 J1 关节相对增加 1 度，并生成需要确认的动作候选',
    })));
    const terminalMessage = await voiceInbox.waitFor(
      message => message.type === 'intent.candidate' || message.type === 'session.completed',
      'Voice candidate or completion'
    );
    const candidateMessage = terminalMessage.type === 'intent.candidate'
      ? terminalMessage
      : voiceInbox.messages.find(message => message.type === 'intent.candidate');
    if (!candidateMessage) {
      const assistantText = voiceInbox.messages
        .filter(message => message.type === 'assistant.response')
        .map(message => message.payload?.text)
        .filter(Boolean);
      throw new Error(`Voice completed without candidate; assistant=${JSON.stringify(assistantText)}`);
    }
    candidate = candidateMessage.payload;
  }
  assert.equal(candidate.skill, 'manual_joint_control@1');
  assert.equal(candidate.intent, 'joint.step');
  assert.equal(candidate.payload.params.action, 'joint.step');
  assert.equal(candidate.payload.params.joint, 1);
  assert.equal(candidate.payload.params.deltaDeg, 1);
  assert.equal(candidate.requiresConfirmation, true);
  assert.ok(candidate.candidateId && candidate.traceId);
  assert.ok(candidate.expiresAt > Date.now());
  assert.ok(candidate.expiresAt - candidate.createdAt <= 120000);

  web.send(JSON.stringify({ type: 'skill.candidate', candidate }));
  await webInbox.waitFor(
    message => message.type === 'skill.candidate.registered' && message.candidateId === candidate.candidateId,
    'candidate registration'
  );
  web.send(JSON.stringify({
    type: 'confirmation.decision',
    candidateId: candidate.candidateId,
    traceId: candidate.traceId,
    decision: 'approve',
  }));
  const result = await webInbox.waitFor(
    message => message.type === 'skill.result' && message.candidateId === candidate.candidateId,
    'blocked skill.result'
  );
  assert.equal(result.success, false);
  assert.equal(result.status, 'blocked');
  assert.match(result.message, /LANGUAGE_REAL_CONTROL/);
  assert.equal(
    webInbox.messages.some(message => message.type === 'execution.request' && message.candidateId === candidate.candidateId),
    false
  );

  voiceSocket?.close();
  web.close();
  console.log(process.env.STAGING_SKIP_VOICE === '1'
    ? `PASS staging contract candidate -> ${webEndpoint} confirmation gate`
    : `PASS staging ${voiceEndpoint} -> candidate -> ${webEndpoint} confirmation gate`);
  console.log('PASS LANGUAGE_REAL_CONTROL=0 emitted no execution.request');
}

main().catch(error => {
  console.error('FAIL', error);
  process.exitCode = 1;
}).finally(() => {
  voiceSocket?.terminate();
  webSocket?.terminate();
});
