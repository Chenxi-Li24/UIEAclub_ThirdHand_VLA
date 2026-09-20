'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const { RobotWebSocketClient } = require(
  '../../../src/thirdhand_va/action/adapters/robot_ws_client'
);

class FakeSocket extends EventEmitter {
  static OPEN = 1;
  constructor(url) {
    super();
    this.url = url;
    this.readyState = FakeSocket.OPEN;
    this.sent = [];
    FakeSocket.instance = this;
  }
  send(value) { this.sent.push(JSON.parse(value)); }
  close() { this.readyState = 3; this.emit('close'); }
}

function completeHandshake() {
  const request = FakeSocket.instance.sent.at(-1);
  assert.equal(request.type, 'capability_request');
  const response = {
    type: 'capability_response',
    schema: 'thirdhand-robot-capability-v1',
    nonce: request.nonce,
    protocol_version: 'thirdhand-robot-lowlevel-v1',
    pose_frame: 'robot_flange',
    commands: ['move_l', 'move_joint', 'gripper', 'preset', 'software_stop', 'get_state'],
    correlated_completions: true,
    software_stop_ack: true,
    software_stop_state_boundary: true,
    state_units: {
      position: 'm', orientation: 'rad', joints: 'deg',
      joint_velocity: 'deg/s', gripper: 'm',
    },
    state_stream: {
      sequence: 'uint53', producer_monotonic_ns: 'uint53', strictly_increasing: true,
    },
    state_sequence: 0,
    producer_monotonic_ns: 500,
  };
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(response)));
  return response;
}

test('robot websocket adapter permits only low-level commands and correlates replies', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  assert.equal(client.protocolReady, false);
  assert.equal(client.send({ cmd: 'get_state' }), false);
  completeHandshake();
  assert.equal(client.protocolReady, true);

  assert.equal(client.send({ cmd: 'closed_loop_pick', target_index: 2 }), false);
  assert.equal(client.send({
    cmd: 'move_l', position: [0.4, 0, 0.2], request_id: 'move-1',
  }), true);
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_status', status: 'accepted', command: 'move_l', request_id: 'move-1',
  })));
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_status', status: 'complete', command: 'move_l',
    request_id: 'move-1', reached: true,
  })));

  assert.equal(FakeSocket.instance.sent.some(item => item.cmd === 'closed_loop_pick'), false);
  assert.equal(events.at(-1).type, 'command_complete');
  assert.equal(events.at(-1).request_id, 'move-1');
});

test('robot state is normalized for controllers and camera timestamps', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws', nowNs: () => 900n,
  });
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'robot_state', connected: true, moving: false,
    pose_frame: 'robot_flange',
    state_sequence: 1, producer_monotonic_ns: 600,
    flange_position_m: [0.4, 0, 0.2], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 1, 2, 3, 4, 5], velocities_deg_s: [0, 0, 0, 0, 0, 0],
    gripper_width_m: 0.06, healthy: true,
  })));

  assert.deepEqual(client.getRobotState(), {
    connected: true, moving: false, stationary: true, stateFresh: true,
    healthy: true, poseFrame: 'robot_flange',
    flangePositionM: [0.4, 0, 0.2], flangeEulerRad: [0, 0, 0],
    jointsDeg: [0, 1, 2, 3, 4, 5], velocitiesDegS: [0, 0, 0, 0, 0, 0],
    gripperWidthM: 0.06, stateSequence: 1, producerMonotonicNs: 600,
    observedMonotonicNs: 900,
  });
});

test('capability handshake rejects an implicit pose frame', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  client.connect();
  FakeSocket.instance.emit('open');
  const response = completeHandshake();

  assert.equal(client.protocolReady, true);
  client.shutdown();

  const second = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  second.connect();
  FakeSocket.instance.emit('open');
  delete response.pose_frame;
  response.nonce = FakeSocket.instance.sent.at(-1).nonce;
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(response)));
  assert.equal(second.protocolReady, false);
});

test('robot state becomes fail-closed when the observation is stale', () => {
  let now = 1_000_000_000n;
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket,
    url: 'ws://127.0.0.1:3000/ws',
    nowNs: () => now,
    maxStateAgeMs: 250,
  });
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'robot_state', connected: true, moving: false,
    state_sequence: 1, producer_monotonic_ns: 600,
    pose_frame: 'robot_flange',
    flange_position_m: [0.4, 0, 0.2], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 1, 2, 3, 4, 5], velocities_deg_s: [0, 0, 0, 0, 0, 0],
    gripper_width_m: 0.06, healthy: true,
  })));
  now += 251_000_000n;

  assert.equal(client.getRobotState().stateFresh, false);
});

test('robot state rejects replay and never calls nonzero velocity stationary', () => {
  let now = 1_000n;
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws', nowNs: () => now,
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  const state = {
    type: 'robot_state', connected: true, moving: false,
    state_sequence: 1, producer_monotonic_ns: 600,
    pose_frame: 'robot_flange',
    flange_position_m: [0.4, 0, 0.2], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 1, 2, 3, 4, 5], velocities_deg_s: [0, 0, 0.6, 0, 0, 0],
    gripper_width_m: 0.06, healthy: true,
  };
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(state)));
  assert.equal(client.getRobotState().stationary, false);

  now = 1_001n;
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    ...state, velocities_deg_s: [0, 0, 0, 0, 0, 0],
  })));
  assert.equal(events.at(-1).type, 'error');
  assert.equal(events.at(-1).reason, 'robot_state_invalid');
  assert.equal(client.getRobotState().observedMonotonicNs, 1_000);
});

test('successful capability handshake cannot be replayed to reset state baselines', () => {
  let now = 1_000n;
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws', nowNs: () => now,
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  const handshake = completeHandshake();
  const state = {
    type: 'robot_state', connected: true, moving: false,
    state_sequence: 1, producer_monotonic_ns: 600,
    pose_frame: 'robot_flange',
    flange_position_m: [0.4, 0, 0.2], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 1, 2, 3, 4, 5], velocities_deg_s: [0, 0, 0, 0, 0, 0],
    gripper_width_m: 0.06, healthy: true,
  };
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(state)));
  now = 1_001n;
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(handshake)));
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify(state)));

  assert.equal(client.protocolReady, true);
  assert.equal(client.getRobotState().stateSequence, 1);
  assert.equal(events.filter(event => event.reason === 'capability_response_unexpected').length, 1);
  assert.equal(events.at(-1).reason, 'robot_state_invalid');
});

test('direct motion completion without reached true is normalized fail-closed', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  assert.equal(client.send({ cmd: 'move_l', request_id: 'move-direct' }), true);

  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_complete', command: 'move_l', request_id: 'move-direct',
  })));

  assert.equal(events.at(-1).type, 'command_complete');
  assert.equal(events.at(-1).reached, false);
});

test('uncorrelated completion can never inherit the in-flight request', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  assert.equal(client.send({ cmd: 'move_l', request_id: 'move-strict' }), true);

  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_status', status: 'complete', reached: true,
  })));

  assert.equal(events.at(-1).type, 'error');
  assert.equal(events.at(-1).reason, 'command_response_uncorrelated');
  assert.equal(client.inFlight.requestId, 'move-strict');
});

test('software stop requires its own correlated stopped acknowledgement', () => {
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws',
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();

  assert.equal(client.send({
    cmd: 'software_stop', request_id: 'stop-1', reason: 'operator_stop',
  }), true);
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_status', status: 'complete', command: 'software_stop',
    request_id: 'stop-1', stopped: true,
    applied_state_sequence: 4, applied_producer_monotonic_ns: 900,
  })));

  assert.equal(events.at(-1).type, 'command_complete');
  assert.equal(events.at(-1).stopped, true);
  assert.equal(events.at(-1).applied_state_sequence, 4);
  assert.equal(client.stopInFlight, null);
});

test('software stop rejects an applied boundary older than state known at send time', () => {
  let now = 1_000n;
  const client = new RobotWebSocketClient({
    WebSocketImpl: FakeSocket, url: 'ws://127.0.0.1:3000/ws', nowNs: () => now,
  });
  const events = [];
  client.on('event', event => events.push(event));
  client.connect();
  FakeSocket.instance.emit('open');
  completeHandshake();
  now = 1_100n;
  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'robot_state', connected: true, moving: true,
    state_sequence: 10, producer_monotonic_ns: 600,
    pose_frame: 'robot_flange',
    flange_position_m: [0.4, 0, 0.2], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 1, 2, 3, 4, 5], velocities_deg_s: [1, 0, 0, 0, 0, 0],
    gripper_width_m: 0.06, healthy: true,
  })));
  assert.equal(client.send({
    cmd: 'software_stop', request_id: 'stop-old-boundary', reason: 'operator_stop',
  }), true);

  FakeSocket.instance.emit('message', Buffer.from(JSON.stringify({
    type: 'command_complete', command: 'software_stop',
    request_id: 'stop-old-boundary', stopped: true,
    applied_state_sequence: 9, applied_producer_monotonic_ns: 599,
  })));

  assert.equal(events.at(-1).type, 'command_complete');
  assert.equal(events.at(-1).stopped, false);
  assert.equal(events.at(-1).applied_state_sequence, undefined);
});
