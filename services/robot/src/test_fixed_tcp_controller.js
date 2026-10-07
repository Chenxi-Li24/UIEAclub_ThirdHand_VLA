'use strict';

const assert = require('node:assert/strict');
const { RobotController } = require('./robot-controller');

const controller = new RobotController({ speedScale: 0.05 });
controller.bridge.connected = true;
controller.bridge.ready = true;
controller.stateReady = true;
controller.latestJointsDeg = [0, 0, 0, 0, 0, 0];
controller.latestRobotStateAtMs = Date.now();
let sent;
controller.bridge.send = command => { sent = command; return true; };
let reply;
const send = message => controller.handleCommand(message, value => { reply = value; });

send({ cmd: 'fixed_tcp_demo', request_id: 'demo-1', execute: false });
assert.equal(sent.cmd, 'fixed_tcp_demo');
assert.equal(sent.execute, false);
assert.deepEqual(sent.fixed_xyz, [0.48, 0, 0.36]);
assert.equal(controller.demoActiveRequestId, 'demo-1');

send({ cmd: 'fixed_tcp_demo', request_id: 'demo-2', execute: true });
assert.equal(reply.code, 'fixed_tcp_demo_active');
send({ cmd: 'move_joint', joints_deg: [1, 0, 0, 0, 0, 0] });
assert.equal(reply.code, 'fixed_tcp_demo_active');

controller._handleBridgeMessage({ type: 'command_complete', request_id: 'demo-1',
  command: 'fixed_tcp_demo' });
assert.equal(controller.demoActiveRequestId, null);

sent = null;
send({ cmd: 'fixed_tcp_demo', request_id: 'bad', execute: true, max_cone_deg: 90 });
assert.equal(reply.code, 'fixed_tcp_demo_invalid');
assert.equal(sent, null);

console.log('3000 fixed TCP command: OK');
