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
  service.controller.bridge.softwareStop = () => {
    stopCalls += 1;
    setTimeout(() => service.controller.bridge.emit('software_stop_complete', { ts: Date.now() }), 30);
    return true;
  };

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

function alignmentPrimitive(startJointsDeg, changes = {}) {
  const parameters = {
    sessionId: 'session-1', stableId: 2, frameId: 41,
    evidenceId: `sha256:${'b'.repeat(64)}`, motionEpoch: 3,
    tier: 'wrist', wristExhausted: false,
    startJointsDeg: [...startJointsDeg],
    targetJointsDeg: startJointsDeg.map((value, index) => index === 4 ? value + 1 : value),
    timeoutMs: 3000,
    ...(changes.parameters || {}),
  };
  return {
    schema: 'thirdhand.execution-primitive.v1', primitiveId: changes.primitiveId || 'align-1',
    traceId: 'trace-1', taskId: 'active-depth:session-1',
    authorizationId: 'active-depth:session-1', planDigest: `sha256:${'a'.repeat(64)}`,
    operation: 'vision.align.step', parameters,
  };
}

async function connectedExecutionService(t, name) {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), `thirdhand-${name}-`));
  const service = createRobotService(robotOptions(runtime));
  t.after(async () => { await service.close(); fs.rmSync(runtime, { recursive: true, force: true }); });
  const address = await service.start();
  const manual = await openSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(() => manual.close());
  const connected = nextMessage(manual, message => message.type === 'connection' && message.connected);
  manual.send(JSON.stringify({ cmd: 'connect' }));
  await connected;
  const statePromise = nextMessage(manual, message => message.type === 'robot_state');
  manual.send(JSON.stringify({ cmd: 'status' }));
  const state = await statePromise;
  const execution = await openSocket(`ws://127.0.0.1:${address.port}/execution`, {
    headers: { 'x-thirdhand-execution-token': 'a'.repeat(64) },
  });
  t.after(() => execution.close());
  return { service, execution, joints: state.joints_deg };
}

test('bounded wrist and exhausted-arm alignment primitives execute one joint command', async (t) => {
  const { service, execution, joints } = await connectedExecutionService(t, 'alignment-valid');
  const sent = [];
  const originalSend = service.controller.bridge.send.bind(service.controller.bridge);
  service.controller.bridge.send = message => {
    if (message.cmd === 'move_joint') sent.push(message);
    return originalSend(message);
  };

  const wrist = alignmentPrimitive(joints);
  const wristDone = nextMessage(execution, message => message.type === 'execution.status'
    && (message.primitiveId === wrist.primitiveId || message.code === 'primitive_invalid')
    && message.status !== 'accepted');
  execution.send(JSON.stringify(wrist));
  const wristResult = await wristDone;
  assert.equal(wristResult.code, 'target_reached', JSON.stringify(wristResult));

  const fresh = [...service.controller.latestJointsDeg];
  const arm = alignmentPrimitive(fresh, {
    primitiveId: 'align-2',
    parameters: {
      tier: 'arm_fallback', wristExhausted: true,
      targetJointsDeg: fresh.map((value, index) => index === 0 ? value + 0.5 : value),
      motionEpoch: 4, frameId: 42,
    },
  });
  const armDone = nextMessage(execution, message => message.primitiveId === arm.primitiveId && message.status === 'completed');
  execution.send(JSON.stringify(arm));
  assert.equal((await armDone).code, 'target_reached');
  assert.equal(sent.length, 2);
  assert.ok(sent.every(message => message.cmd === 'move_joint'));
});

test('Robot Service rejects stale, mixed-tier, oversized, and unexhausted fallback alignment', async (t) => {
  const { service, execution, joints } = await connectedExecutionService(t, 'alignment-invalid');
  let moveCalls = 0;
  const originalSend = service.controller.bridge.send.bind(service.controller.bridge);
  service.controller.bridge.send = message => {
    if (message.cmd === 'move_joint') moveCalls += 1;
    return originalSend(message);
  };
  const cases = [
    ['stale_start_joints', { startJointsDeg: joints.map((value, index) => index === 0 ? value + 1 : value) }],
    ['mixed_joint_tiers', { targetJointsDeg: joints.map((value, index) => [0, 4].includes(index) ? value + 0.5 : value) }],
    ['joint_step_exceeded', { targetJointsDeg: joints.map((value, index) => index === 4 ? value + 4.1 : value) }],
    ['wrist_not_exhausted', { tier: 'arm_fallback', wristExhausted: false,
      targetJointsDeg: joints.map((value, index) => index === 0 ? value + 0.5 : value) }],
  ];
  for (const [code, parameters] of cases) {
    const primitive = alignmentPrimitive(joints, { primitiveId: `bad-${code}`, parameters });
    const failed = nextMessage(execution, message => message.status === 'failed'
      && (message.primitiveId === primitive.primitiveId || message.code === 'primitive_invalid'));
    execution.send(JSON.stringify(primitive));
    assert.equal((await failed).code, code);
  }
  assert.equal(moveCalls, 0);
});

test('exact session stop interrupts alignment and malformed control cannot move', async (t) => {
  const { service, execution, joints } = await connectedExecutionService(t, 'alignment-stop');
  let stopCalls = 0;
  service.controller.bridge.send = message => message.cmd === 'move_joint';
  service.controller.bridge.softwareStop = () => {
    stopCalls += 1;
    setTimeout(() => service.controller.bridge.emit('software_stop_complete', { ts: Date.now() }), 30);
    return true;
  };
  const primitive = alignmentPrimitive(joints);
  const accepted = nextMessage(execution, message => message.type === 'execution.status'
    && (message.primitiveId === primitive.primitiveId || message.code === 'primitive_invalid'));
  execution.send(JSON.stringify(primitive));
  assert.equal((await accepted).status, 'accepted');
  const interrupted = nextMessage(execution, message => message.primitiveId === primitive.primitiveId && message.status === 'interrupted');
  const stopStartedAt = Date.now();
  execution.send(JSON.stringify({
    schema: 'thirdhand.execution-control.v1', type: 'execution.stop',
    sessionId: 'session-1', reason: 'operator_stop',
  }));
  setTimeout(() => {
    service.controller.bridge.emit('message', {
      type: 'command_complete', request_id: `execution:${primitive.primitiveId}`, reached: true,
    });
    service.controller.bridge.emit('message', {
      type: 'robot_state', state: 'IDLE', ts: Date.now(),
      joints_rad: primitive.parameters.targetJointsDeg.map(value => value * Math.PI / 180),
      velocities_rad_s: [0,0,0,0,0,0], tcp_position_m: [0,0,0], tcp_euler_rad: [0,0,0],
    });
  }, 10);
  assert.equal((await interrupted).code, 'operator_stop');
  assert.ok(Date.now() - stopStartedAt >= 20, 'terminal status waits for software-stop acknowledgement');
  assert.equal(stopCalls, 1);

  const invalid = nextMessage(execution, message => message.code === 'invalid_execution_control');
  execution.send(JSON.stringify({
    schema: 'thirdhand.execution-control.v1', type: 'execution.stop',
    sessionId: 'session-1', reason: 'operator_stop', extra: true,
  }));
  assert.equal((await invalid).status, 'failed');
});
