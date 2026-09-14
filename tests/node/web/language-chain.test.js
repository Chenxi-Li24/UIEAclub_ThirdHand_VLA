'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { WebSocket, WebSocketServer } = require('ws');

const { createWebGateway } = require('../../../apps/web/src/server');

function inbox(socket) {
  const messages = [];
  const waiters = [];
  socket.on('message', data => {
    const message = JSON.parse(data.toString('utf8'));
    const index = waiters.findIndex(item => item.predicate(message));
    if (index >= 0) {
      const [waiter] = waiters.splice(index, 1);
      clearTimeout(waiter.timer);
      waiter.resolve(message);
      return;
    }
    messages.push(message);
  });
  return predicate => {
    const index = messages.findIndex(predicate);
    if (index >= 0) return Promise.resolve(messages.splice(index, 1)[0]);
    return new Promise((resolve, reject) => {
      const waiter = { predicate, resolve, reject };
      waiter.timer = setTimeout(() => reject(new Error('message timeout')), 3000);
      waiters.push(waiter);
    });
  };
}

async function createRobotStub() {
  const received = [];
  const server = http.createServer();
  const wss = new WebSocketServer({ server });
  wss.on('connection', socket => {
    const sendState = joints => socket.send(JSON.stringify({
      type: 'robot_state',
      joints,
      gripperPosition: 0.2,
      stateName: 'IDLE',
      ts: Date.now(),
    }));
    socket.send(JSON.stringify({
      type: 'config',
      connection: {
        connected: true,
        simulated: false,
        dryRun: false,
        interface: 'can0',
      },
      motion: { speedScale: 0.05 },
      presets: { home: [0, 0, 0, 0, 0, 0] },
      jointLimits: [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
    }));
    sendState([10, 20, -30, 0, 0, 0]);
    socket.on('message', data => {
      const message = JSON.parse(data.toString('utf8'));
      received.push(message);
      if (message.cmd === 'status') {
        sendState([10, 20, -30, 0, 0, 0]);
      }
      if (message.cmd === 'servo') {
        socket.send(JSON.stringify({
          type: 'command_status',
          status: 'accepted',
          command: 'move_joint',
          request_id: 'fake-robot-request-1',
        }));
        socket.send(JSON.stringify({
          type: 'command_status',
          status: 'complete',
          command: 'move_joint',
          request_id: 'fake-robot-request-1',
        }));
        socket.send(JSON.stringify({ type: 'motion_state', stateName: 'IDLE', ts: Date.now() }));
        sendState(message.joints);
      }
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return {
    received,
    url: `ws://127.0.0.1:${server.address().port}/ws`,
    async close() {
      for (const socket of wss.clients) socket.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

function candidate(id, deltaDeg) {
  const now = Date.now();
  return {
    candidateId: id,
    traceId: `trace-${id}`,
    sourceText: `J1增加${deltaDeg}度`,
    skill: 'manual_joint_control@1',
    intent: 'joint.step',
    createdAt: now,
    expiresAt: now + 120_000,
    requiresConfirmation: true,
    payload: { params: { action: 'joint.step', joint: 1, deltaDeg } },
  };
}

test('deliverable Language candidate and confirmation chain reaches only the fake 3000', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-language-chain-'));
  const publicDir = path.join(runtime, 'public');
  const assetsDir = path.join(runtime, 'assets');
  const readyFile = path.join(runtime, 'web.ready');
  fs.mkdirSync(publicDir, { recursive: true });
  fs.mkdirSync(assetsDir, { recursive: true });
  fs.writeFileSync(path.join(publicDir, 'index.html'), '<h1>ThirdHand</h1>');

  const robot = await createRobotStub();
  const gateway = createWebGateway({
    env: {
      ...process.env,
      LANGUAGE_REAL_CONTROL: '1',
      DIRECTIONAL_CONTROL_ENABLED: '1',
      DIRECTIONAL_REAL_CONTROL: '1',
    },
    host: '127.0.0.1',
    port: 0,
    publicDir,
    assetsDir,
    readyFile,
    robotWsUrl: robot.url,
    voiceWsUrl: 'ws://127.0.0.1:9/v1/voice',
    visionHttpUrl: 'http://127.0.0.1:9',
    visionWsUrl: 'ws://127.0.0.1:9/ws',
  });
  t.after(async () => {
    await gateway.close();
    await robot.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await gateway.start();
  const browser = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  const next = inbox(browser);
  await new Promise((resolve, reject) => {
    browser.once('open', resolve);
    browser.once('error', reject);
  });
  t.after(() => browser.terminate());

  await next(message => message.type === 'language_backend' &&
    message.connected === true && message.stateFresh === true);

  const rejectedCandidate = candidate('candidate-reject', 1);
  browser.send(JSON.stringify({ type: 'skill.candidate', candidate: rejectedCandidate }));
  await next(message => message.type === 'skill.candidate.registered' &&
    message.candidateId === rejectedCandidate.candidateId);
  browser.send(JSON.stringify({
    type: 'confirmation.decision',
    candidateId: rejectedCandidate.candidateId,
    traceId: rejectedCandidate.traceId,
    decision: 'reject',
  }));
  const rejected = await next(message => message.type === 'skill.result' &&
    message.candidateId === rejectedCandidate.candidateId);
  assert.equal(rejected.status, 'rejected');
  assert.equal(robot.received.some(message => message.cmd === 'servo'), false);

  const approvedCandidate = candidate('candidate-approve', 1);
  browser.send(JSON.stringify({ type: 'skill.candidate', candidate: approvedCandidate }));
  await next(message => message.type === 'skill.candidate.registered' &&
    message.candidateId === approvedCandidate.candidateId);
  browser.send(JSON.stringify({
    type: 'confirmation.decision',
    candidateId: approvedCandidate.candidateId,
    traceId: approvedCandidate.traceId,
    decision: 'approve',
  }));
  const result = await next(message => message.type === 'skill.result' &&
    message.candidateId === approvedCandidate.candidateId);
  assert.equal(result.success, true, JSON.stringify(result));
  assert.equal(robot.received.filter(message => message.cmd === 'servo').length, 1);
});
