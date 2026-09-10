'use strict';

const assert = require('assert');
const WebSocket = require('ws');

const voiceEndpoint = process.env.REAL_VOICE_WS || 'ws://127.0.0.1:3002/v1/voice';
const webEndpoint = process.env.REAL_WEB_WS || 'ws://127.0.0.1:9981/ws';
const timeoutMs = Number(process.env.REAL_ACCEPTANCE_TIMEOUT_MS || 30000);
const resumeMinusOnly = process.env.REAL_ACCEPTANCE_RESUME_MINUS === '1';
const expectedReturnJ1 = Number(process.env.REAL_EXPECTED_RETURN_J1);
let webSocket;
let executionStarted = false;

function envelope(type, sessionId, payload) {
  return {
    v: 1,
    type,
    messageId: `accept-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    replyTo: null,
    sessionId,
    ts: Date.now(),
    payload,
  };
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
    waitFor(predicate, label, customTimeoutMs = timeoutMs) {
      const existing = messages.find(predicate);
      if (existing) return Promise.resolve(existing);
      return new Promise((resolve, reject) => {
        const waiter = { predicate, resolve, timer: null };
        waiter.timer = setTimeout(() => {
          const index = waiters.indexOf(waiter);
          if (index >= 0) waiters.splice(index, 1);
          reject(new Error(`timeout waiting for ${label}`));
        }, customTimeoutMs);
        waiters.push(waiter);
      });
    },
  };
}

function connect(url, protocols) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, protocols);
    const messages = inbox(socket);
    const timer = setTimeout(() => reject(new Error(`connect timeout: ${url}`)), 10000);
    socket.once('open', () => {
      clearTimeout(timer);
      resolve({ socket, inbox: messages });
    });
    socket.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

async function languageCandidate(text, expectedDeltaDeg) {
  const connection = await connect(voiceEndpoint, ['thirdhand.voice.v1']);
  const sessionId = `j1-accept-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  try {
    connection.socket.send(JSON.stringify(envelope('text.submit', sessionId, { text })));
    await connection.inbox.waitFor(
      message => message.sessionId === sessionId && message.type === 'session.completed',
      'Language completion',
      120000
    );
    const message = connection.inbox.messages.find(
      item => item.sessionId === sessionId && item.type === 'intent.candidate'
    );
    if (!message) throw new Error(`Language returned no candidate for: ${text}`);
    const candidate = message.payload;
    assert.equal(candidate.skill, 'manual_joint_control@1');
    assert.equal(candidate.intent, 'joint.step');
    assert.equal(candidate.requiresConfirmation, true);
    assert.deepEqual(candidate.payload.params, {
      action: 'joint.step',
      joint: 1,
      deltaDeg: expectedDeltaDeg,
    });
    assert.ok(candidate.candidateId && candidate.traceId);
    assert.ok(candidate.expiresAt > Date.now());
    return candidate;
  } finally {
    connection.socket.close();
  }
}

function latestJ1(messages, startIndex = 0) {
  const state = messages.slice(startIndex).filter(
    message => message.type === 'language_backend' && message.backend === 'formal-3000-upstream' &&
      message.connected === true && message.stateFresh === true &&
      Array.isArray(message.joints) && message.joints.length === 6
  ).at(-1);
  if (!state) throw new Error('no fresh six-joint robot_state after execution');
  return Number(state.joints[0]);
}

async function execute(web, candidate, expectedDeltaDeg) {
  const beforeJ1 = latestJ1(web.inbox.messages);
  const expectedTargetJ1 = beforeJ1 + expectedDeltaDeg;
  const startIndex = web.inbox.messages.length;
  web.socket.send(JSON.stringify({ type: 'skill.candidate', candidate }));
  await web.inbox.waitFor(
    message => message.type === 'skill.candidate.registered' && message.candidateId === candidate.candidateId,
    'candidate registration'
  );
  web.socket.send(JSON.stringify({
    type: 'confirmation.decision',
    candidateId: candidate.candidateId,
    traceId: candidate.traceId,
    decision: 'approve',
  }));
  executionStarted = true;
  await web.inbox.waitFor(
    message => message.type === 'execution.request' && message.candidateId === candidate.candidateId,
    'execution request'
  );
  const result = await web.inbox.waitFor(
    message => message.type === 'skill.result' && message.candidateId === candidate.candidateId,
    'verified skill result'
  );
  assert.equal(result.success, true, result.message);
  assert.equal(result.status, 'success');
  assert.equal(result.simulated, false);
  const verifiedState = await web.inbox.waitFor(
    message => message.type === 'language_backend' &&
      message.backend === 'formal-3000-upstream' && message.connected === true &&
      message.stateFresh === true && message.motionActive === false && message.stateName === 'IDLE' &&
      Array.isArray(message.joints) && message.joints.length === 6 &&
      web.inbox.messages.indexOf(message) >= startIndex &&
      Math.abs(Number(message.joints[0]) - expectedTargetJ1) <= 0.5,
    'post-motion real J1 feedback'
  );
  return Number(verifiedState.joints[0]);
}

async function main() {
  const web = await connect(webEndpoint);
  webSocket = web.socket;
  const config = await web.inbox.waitFor(message => message.type === 'config', 'web config');
  assert.equal(config.language.enabled, true, 'LANGUAGE_REAL_CONTROL must be enabled');
  assert.equal(config.language.speedScale, 0.05);
  assert.equal(config.language.maxDeltaDeg, 5);
  assert.equal(config.language.executionBackend, 'formal-3000-upstream');

  const initialState = await web.inbox.waitFor(
    message => message.type === 'language_backend' &&
      message.backend === 'formal-3000-upstream' && message.connected === true &&
      message.stateFresh === true && message.motionActive === false && message.stateName === 'IDLE' &&
      Array.isArray(message.joints) && message.joints.length === 6,
    'fresh IDLE robot state'
  );
  const initialJ1 = Number(initialState.joints[0]);

  if (resumeMinusOnly) {
    assert.ok(Number.isFinite(expectedReturnJ1), 'REAL_EXPECTED_RETURN_J1 is required in resume mode');
    const minus = await languageCandidate('请把 J1 关节减少 1 度。', -1);
    const finalJ1 = await execute(web, minus, -1);
    const returnError = Math.abs(finalJ1 - expectedReturnJ1);
    assert.ok(returnError <= 0.5, `J1 did not return to pre-test position: error=${returnError}`);
    console.log('PASS resumed real Language J1 -1 at speedScale=0.05');
    console.log(
      `J1 resumeStart=${initialJ1.toFixed(3)} final=${finalJ1.toFixed(3)} ` +
      `expectedReturn=${expectedReturnJ1.toFixed(3)}`
    );
    return;
  }

  const plus = await languageCandidate(
    '请把 J1 关节增加 1 度。',
    1
  );
  const plusJ1 = await execute(web, plus, 1);
  const observedPlus = plusJ1 - initialJ1;
  assert.ok(observedPlus >= 0.5 && observedPlus <= 1.5, `unexpected J1 increase: ${observedPlus}`);

  const minus = await languageCandidate(
    '请把 J1 关节减少 1 度。',
    -1
  );
  const finalJ1 = await execute(web, minus, -1);
  const returnError = Math.abs(finalJ1 - initialJ1);
  assert.ok(returnError <= 0.5, `J1 did not return to start: error=${returnError}`);

  console.log(`PASS real Language J1 +1/-1 at speedScale=0.05`);
  console.log(`J1 initial=${initialJ1.toFixed(3)} plus=${plusJ1.toFixed(3)} final=${finalJ1.toFixed(3)}`);
}

main().catch(error => {
  console.error('FAIL', error);
  if (executionStarted && webSocket?.readyState === WebSocket.OPEN) {
    const now = Date.now();
    webSocket.send(JSON.stringify({
      type: 'skill.candidate',
      candidate: {
        candidateId: `acceptance-stop-${now}`,
        traceId: `acceptance-stop-${now}`,
        sourceText: 'acceptance failure software stop',
        skill: 'manual_joint_control@1',
        requiresConfirmation: false,
        expiresAt: now + 30000,
        payload: { params: { action: 'safety.stop.request' } },
      },
    }));
  }
  process.exitCode = 1;
}).finally(() => {
  setTimeout(() => webSocket?.terminate(), 500);
});
