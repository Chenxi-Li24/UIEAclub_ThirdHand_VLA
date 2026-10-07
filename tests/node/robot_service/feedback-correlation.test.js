'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { RobotController } = require('../../../services/robot/src/robot-controller');

test('busy and validation rejections carry the originating request ID', () => {
  const controller = new RobotController({});
  const replies = [];
  controller.handleCommand({ cmd: 'move_joint', joints_deg: [0], request_id: 'bad-target' }, r => replies.push(r));
  controller.handleCommand({ cmd: 'move_joint', joints_deg: [1, 0, -1, 0, 0, 0], request_id: 'not-ready' }, r => replies.push(r));
  assert.equal(replies.length, 2);
  assert.equal(replies[0].request_id, 'bad-target');
  assert.equal(replies[1].request_id, 'not-ready');
  assert.ok(replies.every(r => r.type === 'error'));
});

test('SDK rejection clears its pending request and broadcasts exactly once', () => {
  const controller = new RobotController({});
  controller.pendingLowLevel.set('req', 'move_joint');
  const replies = [];
  controller.on('message', message => replies.push(message));
  controller.bridge._handleLine(JSON.stringify({ type: 'error', message: 'busy', request_id: 'req' }));
  assert.equal(controller.pendingLowLevel.size, 0);
  assert.equal(replies.length, 1);
  assert.equal(replies[0].request_id, 'req');
});
