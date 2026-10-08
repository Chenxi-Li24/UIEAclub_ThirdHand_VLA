'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { once } = require('node:events');
const { WebSocket } = require('ws');
const { RobotController } = require('../../../services/robot/src/robot-controller');
const { createRobotService } = require('../../../services/robot/src/server');

test('saved deployment fixed TCP command contracts run without hardware', () => {
  require('../../../services/robot/src/test_fixed_tcp_controller');
});

test('fixed TCP demo excludes a concurrent continuous follow stream', () => {
  const controller = new RobotController({ speedScale: 0.05 });
  controller.bridge.connected = controller.stateReady = true;
  controller.latestJointsDeg = [0, 0, 0, 0, 0, 0];
  controller.latestRobotStateAtMs = Date.now();
  controller.bridge.send = () => true;
  controller.handleCommand({ cmd: 'fixed_tcp_demo', request_id: 'demo', execute: false }, () => {});
  let reply;
  controller.handleCommand({ cmd: 'follow_start', stream_id: 'dummy' }, value => { reply = value; }, {});
  assert.equal(reply?.code, 'fixed_tcp_demo_active');
});

test('a rejected duplicate request ID does not gain another owners cancellation rights', () => {
  const controller = new RobotController({ speedScale: 0.02 });
  controller.bridge.connected = controller.stateReady = true;
  controller.latestJointsDeg = [0, 0, 0, 0, 0, 0];
  controller.latestRobotStateAtMs = Date.now();
  controller.bridge.send = () => true;
  let stops = 0;
  controller.bridge.softwareStop = () => { stops += 1; return true; };
  controller.handleCommand({ cmd: 'fixed_tcp_demo', request_id: 'shared', execute: false }, () => {}, 'a');
  let rejected;
  controller.handleCommand({ cmd: 'fixed_tcp_demo', request_id: 'shared', execute: false }, value => { rejected = value; }, 'b');
  assert.equal(rejected.code, 'fixed_tcp_demo_active');
  assert.equal(controller.interruptFixedTcpDemo('shared', 'b'), false);
  assert.equal(stops, 0);
  assert.equal(controller.interruptFixedTcpDemo('shared', 'a'), true);
  assert.equal(stops, 1);
});

test('only the admitted socket can cancel a fixed TCP demo on disconnect', { timeout: 5000 }, async t => {
  const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'fixed-tcp-fake-'));
  const service = createRobotService({ host: '127.0.0.1', port: 0,
    readyFile: path.join(runtime, 'ready'), robot: { speedScale: 0.05 } });
  service.controller.start = service.controller.shutdown = async () => {};
  service.controller.bridge.connected = service.controller.stateReady = true;
  service.controller.latestJointsDeg = [0, 0, 0, 0, 0, 0];
  let accepted;
  const admitted = new Promise(resolve => { accepted = resolve; });
  service.controller.bridge.send = () => { accepted(); return true; };
  let stops = 0;
  let stopped;
  const cancellation = new Promise(resolve => { stopped = resolve; });
  service.controller.bridge.softwareStop = () => { stops += 1; stopped(); return true; };
  const address = await service.start();
  const sockets = [];
  t.after(async () => {
    sockets.forEach(socket => socket.terminate());
    await service.close();
    fs.rmSync(runtime, { recursive: true, force: true });
  });
  const a = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  sockets.push(a);
  await once(a, 'open');
  const b = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  sockets.push(b);
  await once(b, 'open');
  service.controller.latestRobotStateAtMs = Date.now();
  a.send(JSON.stringify({ cmd: 'fixed_tcp_demo', request_id: 'shared-socket-id', execute: false }));
  await admitted;
  const rejected = new Promise(resolve => {
    b.on('message', data => {
      const message = JSON.parse(data);
      if (message.code === 'fixed_tcp_demo_active') resolve(message);
    });
  });
  b.send(JSON.stringify({ cmd: 'fixed_tcp_demo', request_id: 'shared-socket-id', execute: false }));
  await rejected;
  b.close();
  await once(b, 'close');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(stops, 0);
  a.close();
  await cancellation;
  assert.equal(stops, 1);
});
