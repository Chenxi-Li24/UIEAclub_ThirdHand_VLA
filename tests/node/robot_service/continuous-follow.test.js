const test = require('node:test');
const assert = require('node:assert/strict');
const { RobotController } = require('../../../services/robot/src/robot-controller');

function controller() {
  const c = new RobotController({ speedScale: .05 });
  c.bridge.connected = c.stateReady = true;
  c.latestJointsDeg = [0, 0, 0, 0, 0, 0];
  c.latestRobotStateAtMs = Date.now();
  c.sent = [];
  c.bridge.send = message => { c.sent.push(message); return true; };
  return c;
}

test('follow belongs to its websocket and ordinary motion remains excluded', () => {
  const c = controller(); const replies = [];
  c.handleCommand({ cmd: 'follow_start', stream_id: 's', request_id: 'start' }, x => replies.push(x), 'owner');
  c._handleBridgeMessage({ type: 'follow_state', active: true, stream_id: 's' });
  c.handleCommand({ cmd: 'follow_target', stream_id: 's', joints_deg: [1,0,0,1,0,0],
    sequence: 1, observed_at_ms: Date.now() }, x => replies.push(x), 'other');
  assert.equal(replies.at(-1).code, 'follow_stream_mismatch');
  c.handleCommand({ cmd: 'move_joint', joints_deg: [1,0,0,1,0,0] }, x => replies.push(x));
  assert.equal(replies.at(-1).code, 'motion_active');
  c.releaseFollow('other'); assert.equal(c.sent.length, 1);
  c.releaseFollow('owner'); assert.equal(c.sent.at(-1).cmd, 'follow_stop');
});

test('stale follow update is rejected and measured completion is forwarded', () => {
  const c = controller(); const replies = []; const events = [];
  c.on('message', m => events.push(m));
  c.handleCommand({ cmd: 'follow_start', stream_id: 's' }, x => replies.push(x), 'owner');
  c.handleCommand({ cmd: 'follow_target', stream_id: 's', sequence: 1,
    joints_deg: [1,0,0,1,0,0], observed_at_ms: Date.now() - 1000 }, x => replies.push(x), 'owner');
  assert.equal(replies.at(-1).code, 'follow_target_invalid');
  c._handleBridgeMessage({ type: 'command_complete', command: 'move_joint',
    reached: false, actual_joints_rad: [.1,0,0,0,0,0] });
  assert.equal(events.at(-1).reached, false);
  assert.ok(Math.abs(events.at(-1).actual_joints_deg[0] - .1*180/Math.PI) < 1e-9);
});
