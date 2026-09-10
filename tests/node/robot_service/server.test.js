const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { createRobotService } = require('../../../services/robot/src/server');

function nextMessage(socket, predicate, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      socket.removeEventListener('message', onMessage);
      reject(new Error('message timeout'));
    }, timeoutMs);
    function onMessage(event) {
      const message = JSON.parse(String(event.data));
      if (!predicate(message)) return;
      clearTimeout(timer);
      socket.removeEventListener('message', onMessage);
      resolve(message);
    }
    socket.addEventListener('message', onMessage);
  });
}

test('robot service stays disconnected until explicit connect', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-robot-'));
  const readyFile = path.join(runtime, 'robot.ready');
  const service = createRobotService({
    host: '127.0.0.1',
    port: 0,
    readyFile,
    robot: {
      python: 'python3',
      sdkPath: path.resolve('local/sdk/startouch'),
      canInterface: 'can0',
      gripper: true,
      requireCanRx: false,
      canRxStaleSec: 1,
      simulate: true,
      dryRun: false,
      pollIntervalMs: 20,
      jointLogIntervalMs: 1000,
      initSettleSec: 0,
      initSampleCount: 2,
      initMaxDriftDeg: 2,
      speedScale: 1,
      minMoveTimeSec: 0.05,
      maxMoveTimeSec: 2,
    },
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });

  const address = await service.start();
  assert.equal(fs.existsSync(readyFile), true);

  const health = await fetch(`http://127.0.0.1:${address.port}/health`).then(r => r.json());
  assert.equal(health.status, 'ready');
  assert.equal(health.robot.connected, false);

  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  t.after(() => socket.close());

  const config = await nextMessage(socket, message => message.type === 'config');
  assert.equal(config.connection.connected, false);

  await new Promise(resolve => setTimeout(resolve, 80));
  const stillDisconnected = await fetch(
    `http://127.0.0.1:${address.port}/health`,
  ).then(r => r.json());
  assert.equal(stillDisconnected.robot.connected, false);

  const connectedPromise = nextMessage(
    socket,
    message => message.type === 'connection' && message.connected === true,
  );
  socket.send(JSON.stringify({ cmd: 'connect' }));
  const connected = await connectedPromise;
  assert.equal(connected.simulated, true);

  const statePromise = nextMessage(socket, message => message.type === 'robot_state');
  socket.send(JSON.stringify({ cmd: 'status' }));
  const state = await statePromise;
  assert.equal(state.joints.length, 6);

  const pongPromise = nextMessage(socket, message => message.type === 'pong');
  socket.send(JSON.stringify({ cmd: 'ping' }));
  assert.equal((await pongPromise).type, 'pong');
});

test('robot service rejects commands outside the browser protocol', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-robot-'));
  const service = createRobotService({
    host: '127.0.0.1',
    port: 0,
    readyFile: path.join(runtime, 'robot.ready'),
    robot: {
      python: 'python3',
      sdkPath: path.resolve('local/sdk/startouch'),
      canInterface: 'can0',
      gripper: true,
      requireCanRx: false,
      simulate: true,
      dryRun: false,
      pollIntervalMs: 20,
      jointLogIntervalMs: 1000,
      initSettleSec: 0,
      initSampleCount: 2,
      initMaxDriftDeg: 2,
      speedScale: 1,
      minMoveTimeSec: 0.05,
      maxMoveTimeSec: 2,
    },
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  t.after(() => socket.close());

  await nextMessage(socket, message => message.type === 'config');
  const errorPromise = nextMessage(socket, message => message.type === 'error');
  socket.send(JSON.stringify({ cmd: 'start_vision_grasp' }));
  const error = await errorPromise;
  assert.equal(error.code, 'unsupported_command');
});
