'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { WebSocket } = require('ws');
const { createRobotService } = require('../../../services/robot/src/server');

function nextMessage(socket, predicate, timeoutMs = 4000) {
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

function openSocket(url, options) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url, options);
    socket.once('open', () => resolve(socket));
    socket.once('error', reject);
  });
}

function robotOptions(runtime) {
  return {
    host: '127.0.0.1',
    port: 0,
    readyFile: path.join(runtime, 'robot.ready'),
    executionToken: 'a'.repeat(64),
    robot: {
      python: 'python3', sdkPath: path.resolve('local/sdk/startouch'), canInterface: 'can0',
      gripper: true, requireCanRx: false, canRxStaleSec: 1, simulate: true, dryRun: false,
      pollIntervalMs: 20, jointLogIntervalMs: 1000, initSettleSec: 0,
      initSampleCount: 2, initMaxDriftDeg: 2, speedScale: 1,
      minMoveTimeSec: 0.05, maxMoveTimeSec: 2,
    },
  };
}

test('private execution route requires the configured token', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-execution-auth-'));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const url = `ws://127.0.0.1:${address.port}/execution`;

  await assert.rejects(openSocket(url), /401|Unexpected server response/);
  const socket = await openSocket(url, { headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) } });
  assert.equal(socket.readyState, WebSocket.OPEN);
  socket.close();
  const health = await fetch(`http://127.0.0.1:${address.port}/health`).then(response => response.json());
  assert.deepEqual(health.execution, { available: true, reason: null });
});

test('authorized gripper primitive completes from feedback without arm motion', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-execution-'));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const manual = await openSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(() => manual.close());
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const state = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  await state;

  const execution = await openSocket(`ws://127.0.0.1:${address.port}/execution`, {
    headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) },
  });
  t.after(() => execution.close());
  const primitive = {
    schema: 'thirdhand.execution-primitive.v1',
    primitiveId: 'primitive-1', traceId: 'trace-1', taskId: 'task-1', authorizationId: 'auth-1',
    planDigest: `sha256:${'b'.repeat(64)}`,
    operation: 'gripper.set',
    parameters: { positionPercent: 25, tolerancePercent: 2, timeoutMs: 3000 },
  };
  const completed = nextMessage(execution, message => message.type === 'execution.status' && message.status === 'completed');
  execution.send(JSON.stringify(primitive));
  const result = await completed;
  assert.equal(result.primitiveId, primitive.primitiveId);
  assert.ok(Math.abs(result.actualPercent - 25) <= 2);
  assert.ok(result.maxJointDeltaDeg <= 0.5);

  const replay = nextMessage(execution, message => message.type === 'execution.status' && message.status === 'failed');
  execution.send(JSON.stringify(primitive));
  assert.equal((await replay).code, 'primitive_replayed');
});

test('missing correlated feedback becomes uncertain and is never retried', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-execution-timeout-'));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => { await service.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await service.start();
  const manual = await openSocket(`ws://127.0.0.1:${address.port}/ws`);
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const state = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  await state;
  const originalSend = service.controller.bridge.send.bind(service.controller.bridge);
  service.controller.bridge.send = message => message.cmd === 'gripper' ? true : originalSend(message);

  const execution = await openSocket(`ws://127.0.0.1:${address.port}/execution`, {
    headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) },
  });
  const primitive = {
    schema: 'thirdhand.execution-primitive.v1', primitiveId: 'timeout-1', traceId: 'trace-timeout',
    taskId: 'task-timeout', authorizationId: 'auth-timeout', planDigest: `sha256:${'d'.repeat(64)}`,
    operation: 'gripper.set', parameters: { positionPercent: 50, tolerancePercent: 2, timeoutMs: 100 },
  };
  const terminal = nextMessage(execution, message => message.primitiveId === primitive.primitiveId && message.status === 'uncertain');
  execution.send(JSON.stringify(primitive));
  assert.equal((await terminal).code, 'feedback_timeout');
  assert.equal(service.controller.seenPrimitiveIds.size, 1);
  execution.close();
  manual.close();
});

test('correlated feedback with arm-joint delta fails as unexpected arm motion', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-execution-delta-'));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => { await service.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await service.start();
  const manual = await openSocket(`ws://127.0.0.1:${address.port}/ws`);
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const state = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  await state;
  const originalSend = service.controller.bridge.send.bind(service.controller.bridge);
  service.controller.bridge.send = message => {
    if (message.cmd !== 'gripper') return originalSend(message);
    setTimeout(() => {
      service.controller.latestJointsDeg[0] += 1;
      service.controller.latestRobotStateAtMs = Date.now();
      service.controller.bridge.emit('message', {
        type: 'command_complete', request_id: message.request_id,
        reached: true, actual_position: message.position, ts: Date.now(),
      });
    }, 20);
    return true;
  };
  const execution = await openSocket(`ws://127.0.0.1:${address.port}/execution`, {
    headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) },
  });
  const primitive = {
    schema: 'thirdhand.execution-primitive.v1', primitiveId: 'delta-1', traceId: 'trace-delta',
    taskId: 'task-delta', authorizationId: 'auth-delta', planDigest: `sha256:${'e'.repeat(64)}`,
    operation: 'gripper.set', parameters: { positionPercent: 40, tolerancePercent: 2, timeoutMs: 1000 },
  };
  const terminal = nextMessage(execution, message => message.primitiveId === primitive.primitiveId && message.status === 'failed');
  execution.send(JSON.stringify(primitive));
  const result = await terminal;
  assert.equal(result.code, 'unexpected_arm_motion');
  assert.ok(result.maxJointDeltaDeg > 0.5);
  execution.close();
  manual.close();
});

test('closing an in-flight private execution socket requests software stop', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-execution-close-'));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => { await service.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await service.start();
  const manual = await openSocket(`ws://127.0.0.1:${address.port}/ws`);
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const state = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  await state;
  let stopCalls = 0;
  service.controller.bridge.send = message => message.cmd === 'gripper';
  service.controller.bridge.softwareStop = () => { stopCalls += 1; return true; };

  const execution = await openSocket(`ws://127.0.0.1:${address.port}/execution`, {
    headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) },
  });
  const primitive = {
    schema: 'thirdhand.execution-primitive.v1', primitiveId: 'close-1', traceId: 'trace-close',
    taskId: 'task-close', authorizationId: 'auth-close', planDigest: `sha256:${'f'.repeat(64)}`,
    operation: 'gripper.set', parameters: { positionPercent: 60, tolerancePercent: 2, timeoutMs: 3000 },
  };
  const accepted = nextMessage(execution, message => message.primitiveId === primitive.primitiveId && message.status === 'accepted');
  execution.send(JSON.stringify(primitive));
  await accepted;
  execution.close();
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(stopCalls, 1);
  assert.equal(service.controller.pendingExecutions.size, 0);
  manual.close();
});
