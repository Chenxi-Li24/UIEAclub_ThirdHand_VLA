'use strict';

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

test('TCP preview solves joints without commanding simulated motion', async (t) => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-tcp-'));
  const service = createRobotService({
    host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'robot.ready'),
    robot: {
      python: 'python3', sdkPath: path.resolve('local/sdk/startouch'),
      canInterface: 'can0', gripper: true, requireCanRx: false,
      canRxStaleSec: 1, simulate: true, dryRun: false,
      pollIntervalMs: 20, jointLogIntervalMs: 1000,
      initSettleSec: 0, initSampleCount: 2, initMaxDriftDeg: 2,
      speedScale: 1, minMoveTimeSec: 0.05, maxMoveTimeSec: 2,
    },
  });
  t.after(async () => {
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const address = await service.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(() => socket.close());
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  await nextMessage(socket, message => message.type === 'config');
  const connectedPromise = nextMessage(socket, message =>
    message.type === 'connection' && message.connected === true);
  socket.send(JSON.stringify({ cmd: 'connect' }));
  await connectedPromise;
  const rejectedPromise = nextMessage(socket, message =>
    message.type === 'error' && message.code === 'linear_target_invalid');
  socket.send(JSON.stringify({
    cmd: 'preview_ik', position: [9, 0, 0.25], euler: [0, 0, 0],
    request_id: 'bad-preview',
  }));
  const rejected = await rejectedPromise;
  assert.equal(rejected.request_id, 'bad-preview');
  const resultPromise = nextMessage(socket, message =>
    message.type === 'error' || (message.type === 'ik_preview' && message.request_id === 'preview-1'));
  socket.send(JSON.stringify({
    cmd: 'preview_ik', position: [0.45, 0, 0.25], euler: [0, 0, 0],
    request_id: 'preview-1',
  }));
  const result = await resultPromise;
  assert.equal(result.type, 'ik_preview');
  assert.equal(result.ok, true);
  assert.equal(result.joints_deg.length, 6);
  const statePromise = nextMessage(socket, message => message.type === 'robot_state');
  socket.send(JSON.stringify({ cmd: 'status' }));
  const state = await statePromise;
  assert.equal(state.stateName, 'IDLE');
  assert.deepEqual(state.joints, [0, 0, 0, 0, 0, 0]);
});
