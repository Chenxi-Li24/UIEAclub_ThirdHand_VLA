'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { WebSocket } = require('ws');

const { createOrchestrator } = require('../../../apps/orchestrator/src/server');
const { createWebGateway } = require('../../../apps/web/src/server');
const { createRobotService } = require('../../../services/robot/src/server');

const ROOT = path.resolve(__dirname, '../../..');
const PLAN_PROTOCOL = 'thirdhand.plan.v1';

function nextMessage(socket, predicate, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.off('message', handler);
      reject(new Error('message timeout'));
    }, timeoutMs);
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

function openSocket(url, protocol) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, protocol);
    socket.once('open', () => resolve(socket));
    socket.once('error', reject);
  });
}

async function waitFor(predicate, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  throw new Error('condition timeout');
}

function candidate(id, intent = 'gripper.open') {
  return {
    candidateId: id,
    traceId: `trace-${id}`,
    intent,
    source: 'voice',
    transcript: intent === 'gripper.open' ? '打开夹爪' : '关闭夹爪',
  };
}

test('full Web to Orchestrator to simulated Robot chain is one-use and fail-closed', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-chain-'));
  const token = 'c'.repeat(64);
  const tokenFile = path.join(runtime, 'robot-execution.token');
  fs.writeFileSync(tokenFile, `${token}\n`, { mode: 0o600 });
  let now = Date.now();

  const robot = createRobotService({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'robot.ready'), executionToken: token,
    robot: {
      python: 'python3', sdkPath: path.join(ROOT, 'local/sdk/startouch'), canInterface: 'can0',
      gripper: true, requireCanRx: false, canRxStaleSec: 1, simulate: true, dryRun: false,
      pollIntervalMs: 20, jointLogIntervalMs: 1000, initSettleSec: 0,
      initSampleCount: 2, initMaxDriftDeg: 2, speedScale: 1,
      minMoveTimeSec: 0.05, maxMoveTimeSec: 2,
    },
  });
  const robotAddress = await robot.start();
  const robotOrigin = `http://127.0.0.1:${robotAddress.port}`;
  const robotWs = `ws://127.0.0.1:${robotAddress.port}`;
  const orchestrator = createOrchestrator({
    host: '127.0.0.1', port: 0, readyFile: path.join(runtime, 'orchestrator.ready'),
    robotHealthUrl: robotOrigin,
    robotExecutionWsUrl: `${robotWs}/execution`,
    robotExecutionTokenFile: tokenFile,
    clock: () => now,
  });
  const orchestratorAddress = await orchestrator.start();
  const web = createWebGateway({
    host: '127.0.0.1', port: 0,
    publicDir: path.join(ROOT, 'apps/web/public'), assetsDir: path.join(ROOT, 'assets/robot'),
    readyFile: path.join(runtime, 'web.ready'),
    robotWsUrl: `${robotWs}/ws`,
    orchestratorWsUrl: `ws://127.0.0.1:${orchestratorAddress.port}/plan`,
    voiceWsUrl: 'ws://127.0.0.1:9/voice',
    visionHttpUrl: 'http://127.0.0.1:9', visionWsUrl: 'ws://127.0.0.1:9/vision',
  });
  const webAddress = await web.start();
  const webWs = `ws://127.0.0.1:${webAddress.port}`;
  const sockets = [];
  t.after(async () => {
    for (const socket of sockets) socket.terminate();
    await web.close();
    await orchestrator.close();
    await robot.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const manual = await openSocket(`${webWs}/ws`);
  sockets.push(manual);
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const freshState = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  await freshState;
  now = Date.now();

  const plan = await openSocket(`${webWs}/plan`, PLAN_PROTOCOL);
  sockets.push(plan);
  const beforeGripper = robot.controller.latestGripperPosition;
  const beforeJoints = [...robot.controller.latestJointsDeg];
  plan.send(JSON.stringify({ type: 'candidate.submit', candidate: candidate('happy-1') }));
  const proposed = await nextMessage(plan, message => message.type === 'plan.proposed');
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(robot.controller.latestGripperPosition, beforeGripper);
  assert.equal(robot.controller.seenPrimitiveIds.size, 0);

  const grant = {
    type: 'authorization.grant', proposalId: proposed.proposal.proposalId,
    planId: proposed.proposal.plan.planId, planRevision: proposed.proposal.plan.revision,
    planDigest: proposed.proposal.planDigest,
  };
  const completedPromise = nextMessage(plan, message => message.type === 'skill.result');
  const doubleClickPromise = nextMessage(plan, message => message.type === 'plan.rejected' && message.code === 'authorization_replayed');
  plan.send(JSON.stringify(grant));
  plan.send(JSON.stringify(grant));
  const [completed] = await Promise.all([completedPromise, doubleClickPromise]);
  assert.equal(completed.result.status, 'completed');
  assert.ok(Math.abs(completed.result.output.actualPercent - 100) <= 2);
  assert.ok(completed.result.output.maxJointDeltaDeg <= 0.5);
  assert.equal(robot.controller.seenPrimitiveIds.size, 1);
  assert.ok(robot.controller.latestJointsDeg.every((value, index) => Math.abs(value - beforeJoints[index]) <= 0.5));

  const replayPromise = nextMessage(plan, message => message.type === 'plan.rejected');
  plan.send(JSON.stringify(grant));
  assert.equal((await replayPromise).code, 'authorization_replayed');

  async function expectRejected(testCandidate, code) {
    const socket = await openSocket(`${webWs}/plan`, PLAN_PROTOCOL);
    sockets.push(socket);
    const rejected = nextMessage(socket, message => message.type === 'plan.rejected');
    socket.send(JSON.stringify({ type: 'candidate.submit', candidate: testCandidate }));
    assert.equal((await rejected).code, code);
    socket.close();
  }

  await expectRejected({ candidateId: 'bad-1', traceId: 'trace-bad', intent: 'gripper.open' }, 'message_invalid');
  await expectRejected(candidate('home-1', 'arm.home'), 'unsupported_intent');

  robot.controller.latestRobotStateAtMs = Date.now() - 2000;
  now = Date.now();
  await expectRejected(candidate('stale-1'), 'readiness_unavailable');
  robot.controller.latestRobotStateAtMs = Date.now();
  robot.controller.motionActive = true;
  now = Date.now();
  await expectRejected(candidate('moving-1'), 'readiness_unavailable');
  robot.controller.motionActive = false;

  const expiredSocket = await openSocket(`${webWs}/plan`, PLAN_PROTOCOL);
  sockets.push(expiredSocket);
  now = Date.now();
  expiredSocket.send(JSON.stringify({ type: 'candidate.submit', candidate: candidate('expired-1', 'gripper.close') }));
  const expiredProposal = await nextMessage(expiredSocket, message => message.type === 'plan.proposed');
  now += 31_000;
  const expiredReply = nextMessage(expiredSocket, message => message.type === 'plan.rejected');
  expiredSocket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: expiredProposal.proposal.proposalId,
    planId: expiredProposal.proposal.plan.planId, planRevision: expiredProposal.proposal.plan.revision,
    planDigest: expiredProposal.proposal.planDigest,
  }));
  assert.equal((await expiredReply).code, 'proposal_expired');
  expiredSocket.close();

  now = Date.now();
  robot.controller.latestRobotStateAtMs = now;
  const disconnectSocket = await openSocket(`${webWs}/plan`, PLAN_PROTOCOL);
  sockets.push(disconnectSocket);
  disconnectSocket.send(JSON.stringify({ type: 'candidate.submit', candidate: candidate('disconnect-1', 'gripper.close') }));
  const disconnectProposal = await nextMessage(disconnectSocket, message => message.type === 'plan.proposed');
  const changedDigestReply = nextMessage(disconnectSocket, message => message.type === 'plan.rejected');
  disconnectSocket.send(JSON.stringify({
    type: 'authorization.grant', proposalId: disconnectProposal.proposal.proposalId,
    planId: disconnectProposal.proposal.plan.planId, planRevision: disconnectProposal.proposal.plan.revision,
    planDigest: `sha256:${'0'.repeat(64)}`,
  }));
  assert.equal((await changedDigestReply).code, 'plan_digest_mismatch');
  disconnectSocket.close();
  await waitFor(() => orchestrator.engine.getTask(disconnectProposal.proposal.plan.taskId)?.state === 'interrupted');
});
