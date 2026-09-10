'use strict';

const assert = require('assert');
const { EventEmitter } = require('events');
const {
  LanguageUpstreamBridge,
  normalizeEndpoint,
} = require('../language-upstream-bridge');
const { ManualJointOrchestrator } = require('../manual-joint-control');

class FakeWebSocket extends EventEmitter {
  static OPEN = 1;
  static instances = [];

  constructor(url) {
    super();
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.emit('open');
  }

  send(value) {
    this.sent.push(JSON.parse(value));
  }

  receive(message) {
    this.emit('message', Buffer.from(JSON.stringify(message)));
  }

  close() {
    this.readyState = 3;
    this.emit('close');
  }
}

function makeBridge() {
  FakeWebSocket.instances = [];
  let now = 1_000;
  const bridge = new LanguageUpstreamBridge({
    endpoint: 'ws://127.0.0.1:3000/ws',
    WebSocketImpl: FakeWebSocket,
    now: () => now,
    schedule: () => 99,
    cancelSchedule: () => {},
  });
  bridge.start();
  const socket = FakeWebSocket.instances[0];
  socket.open();
  socket.receive({
    type: 'config',
    connection: { connected: true, simulated: false },
    motion: { speedScale: 0.05 },
    presets: { home: [0, 0, 0, 0, 0, 0] },
  });
  socket.receive({
    type: 'robot_state',
    joints: [10, 20, -30, 0, 0, 0],
    gripperPosition: 0.2,
    stateName: 'IDLE',
  });
  return { bridge, socket, advance: ms => { now += ms; } };
}

assert.strictEqual(normalizeEndpoint('ws://127.0.0.1:3000/ws'), 'ws://127.0.0.1:3000/ws');
assert.throws(() => normalizeEndpoint('ws://192.168.58.68:3000/ws'), /127\.0\.0\.1/);
assert.throws(() => normalizeEndpoint('http://127.0.0.1:3000/ws'), /127\.0\.0\.1/);

{
  const { bridge, socket, advance } = makeBridge();
  const events = [];
  bridge.on('message', message => events.push(message));
  const targetDeg = [11, 20, -30, 0, 0, 0];
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: targetDeg.map(value => value * Math.PI / 180),
    request_id: 'local-joint-1',
  }), true);
  const sent = socket.sent.at(-1);
  assert.strictEqual(sent.cmd, 'servo');
  assert(sent.joints.every((value, index) => Math.abs(value - targetDeg[index]) < 1e-9));
  socket.receive({
    type: 'command_status', status: 'accepted', command: 'move_joint', request_id: 'formal-42',
  });
  advance(100);
  socket.receive({
    type: 'command_status', status: 'complete', command: 'move_joint', request_id: 'formal-42',
  });
  socket.receive({ type: 'motion_state', stateName: 'IDLE' });
  advance(10);
  socket.receive({ type: 'robot_state', joints: targetDeg, stateName: 'IDLE' });
  assert(events.some(event => event.type === 'command_accepted' && event.request_id === 'local-joint-1'));
  assert(events.some(event => event.type === 'command_complete' && event.request_id === 'local-joint-1'));
  assert.strictEqual(bridge.inFlight, null);
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  const upstreamMessages = [];
  bridge.on('upstream_message', message => upstreamMessages.push(message));
  assert.deepStrictEqual(bridge.manualConnectionInfo(), {
    mode: 'startouch-upstream',
    host: '127.0.0.1',
    interface: 'can0',
    connected: true,
    ready: true,
    simulated: false,
    dryRun: false,
  });
  const manualCommands = [
    { cmd: 'servo', joints: [11, 21, -30, 1, 2, 3] },
    { cmd: 'preset', name: 'home' },
    { cmd: 'gripper', position: 0.75 },
    { cmd: 'disconnect' },
    { cmd: 'connect' },
    { cmd: 'status' },
  ];
  for (const command of manualCommands) {
    assert.strictEqual(bridge.sendManual(command), true);
    assert.deepStrictEqual(socket.sent.at(-1), command);
  }
  assert.strictEqual(bridge.sendManual({ cmd: 'move_joint' }), false);
  const robotState = {
    type: 'robot_state',
    joints: [11, 21, -30, 1, 2, 3],
    velocities: [0, 0, 0, 0, 0, 0],
    tcpPos: [100, 200, 300],
    tcpEuler: [0, 0, 0],
    gripperPosition: 0.75,
    stateName: 'IDLE',
  };
  socket.receive(robotState);
  assert.deepStrictEqual(upstreamMessages.at(-1), robotState);
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  const targetDeg = [30, 40, -50, 0, 0, 0];
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: targetDeg.map(value => value * Math.PI / 180),
    request_id: 'authorized-compound-lift-left',
    directional_authorization: {
      skill: 'directional_joint_control@1',
      moves: [
        { action: 'lift.up', deltaDeg: 20 },
        { action: 'turn.left', deltaDeg: 20 },
      ],
    },
  }), true);
  assert.strictEqual(socket.sent.at(-1).cmd, 'servo');
  assert(socket.sent.at(-1).joints.every(
    (value, index) => Math.abs(value - targetDeg[index]) < 1e-9
  ));
  bridge.shutdown();
}

{
  const invalidAuthorizations = [
    {
      targetDeg: [30, 40, -50, 0, 0, 0],
      moves: [
        { action: 'turn.left', deltaDeg: 20 },
        { action: 'turn.right', deltaDeg: 20 },
      ],
    },
    {
      targetDeg: [30, 40, -40, 0, 0, 0],
      moves: [
        { action: 'lift.up', deltaDeg: 20 },
        { action: 'turn.left', deltaDeg: 20 },
      ],
    },
  ];
  for (const [index, item] of invalidAuthorizations.entries()) {
    const { bridge } = makeBridge();
    assert.strictEqual(bridge.send({
      cmd: 'move_joint',
      joints_rad: item.targetDeg.map(value => value * Math.PI / 180),
      request_id: `invalid-compound-${index}`,
      directional_authorization: {
        skill: 'directional_joint_control@1',
        moves: item.moves,
      },
    }), false);
    bridge.shutdown();
  }
}

{
  const { bridge } = makeBridge();
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: [30, 20, -30, 0, 0, 0].map(value => value * Math.PI / 180),
    request_id: 'large-single-joint',
  }), true);
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  const targetDeg = [10, 40, -50, 0, 0, 0];
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: targetDeg.map(value => value * Math.PI / 180),
    request_id: 'authorized-lift-up',
    directional_authorization: {
      skill: 'directional_joint_control@1',
      action: 'lift.up',
      deltaDeg: 20,
    },
  }), true);
  assert.deepStrictEqual(socket.sent.at(-1), { cmd: 'servo', joints: targetDeg });
  bridge.shutdown();
}

{
  const { bridge } = makeBridge();
  const invalidTargets = [
    [10, 40, -40, 0, 0, 0],
    [10, 40, -50, 1, 0, 0],
  ];
  for (const [index, targetDeg] of invalidTargets.entries()) {
    assert.strictEqual(bridge.send({
      cmd: 'move_joint',
      joints_rad: targetDeg.map(value => value * Math.PI / 180),
      request_id: `invalid-directional-${index}`,
      directional_authorization: {
        skill: 'directional_joint_control@1',
        action: 'lift.up',
        deltaDeg: 20,
      },
    }), false);
  }
  bridge.shutdown();
}

{
  const { bridge, socket, advance } = makeBridge();
  const events = [];
  bridge.on('message', message => events.push(message));
  assert.deepStrictEqual(bridge.getPreset('home'), [0, 0, 0, 0, 0, 0]);
  assert.strictEqual(bridge.send({
    cmd: 'preset_home', name: 'home', request_id: 'local-home-1',
  }), true);
  assert.deepStrictEqual(socket.sent.at(-1), { cmd: 'preset', name: 'home' });
  socket.receive({
    type: 'command_status', status: 'accepted', command: 'move_joint', request_id: 'formal-home-1',
  });
  advance(100);
  socket.receive({
    type: 'command_status', status: 'complete', command: 'move_joint', request_id: 'formal-home-1',
  });
  socket.receive({ type: 'motion_state', stateName: 'IDLE' });
  advance(10);
  socket.receive({ type: 'robot_state', joints: [0, 0, 0, 0, 0, 0], stateName: 'IDLE' });
  assert(events.some(event => event.type === 'command_complete' && event.request_id === 'local-home-1'));
  assert.strictEqual(bridge.inFlight, null);
  bridge.shutdown();
}

{
  const { bridge } = makeBridge();
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: [11, 21, -30, 0, 0, 0].map(value => value * Math.PI / 180),
    request_id: 'two-joints',
  }), false);
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  const events = [];
  bridge.on('message', message => events.push(message));
  assert.strictEqual(bridge.send({
    cmd: 'move_joint',
    joints_rad: [11, 20, -30, 0, 0, 0].map(value => value * Math.PI / 180),
    request_id: 'overlap',
  }), true);
  socket.receive({ type: 'command_status', status: 'accepted', command: 'gripper', request_id: null });
  assert(events.some(event => event.type === 'error' && event.request_id === 'overlap'));
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  const events = [];
  bridge.on('message', message => events.push(message));
  assert.strictEqual(bridge.send({ cmd: 'gripper', position: 1, request_id: 'local-gripper-1' }), true);
  socket.receive({ type: 'command_status', status: 'accepted', command: 'gripper' });
  socket.receive({
    type: 'command_status', status: 'complete', command: 'gripper', reached: true,
  });
  assert(events.some(event => (
    event.type === 'command_complete' && event.request_id === 'local-gripper-1' && event.reached === true
  )));
  assert.strictEqual(bridge.inFlight, null);
  bridge.shutdown();
}

{
  const { bridge, socket } = makeBridge();
  socket.receive({
    type: 'config',
    connection: { connected: true, simulated: false },
    motion: { speedScale: 0.1 },
  });
  assert.strictEqual(bridge.getRobotState().connected, false);
  bridge.shutdown();
}

{
  const { bridge, socket, advance } = makeBridge();
  const results = [];
  const session = {};
  const orchestrator = new ManualJointOrchestrator({
    enabled: true,
    getRobotState: () => bridge.getRobotState(),
    sendRobot: command => bridge.send(command),
    softwareStop: () => bridge.softwareStop(),
    moveTimeFor: () => 1,
    jointLimitsDeg: [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
    schedule: () => 88,
    cancelSchedule: () => {},
    now: () => 1_000,
    onMessage: (_session, message) => results.push(message),
  });
  bridge.on('message', message => orchestrator.handleBridgeEvent(message));
  const candidate = {
    candidateId: 'candidate-e2e-1',
    traceId: 'trace-e2e-1',
    sourceText: 'J1 增加 1 度',
    skill: 'manual_joint_control@1',
    requiresConfirmation: true,
    expiresAt: 61_000,
    payload: { params: { action: 'joint.step', joint: 1, deltaDeg: 1 } },
  };
  orchestrator.register(session, candidate);
  orchestrator.decide(session, {
    candidateId: candidate.candidateId,
    traceId: candidate.traceId,
    decision: 'approve',
  });
  const servo = socket.sent.at(-1);
  assert.strictEqual(servo.cmd, 'servo');
  socket.receive({
    type: 'command_status', status: 'accepted', command: 'move_joint', request_id: 'formal-e2e-1',
  });
  advance(100);
  socket.receive({
    type: 'command_status', status: 'complete', command: 'move_joint', request_id: 'formal-e2e-1',
  });
  socket.receive({ type: 'motion_state', stateName: 'IDLE' });
  advance(10);
  socket.receive({ type: 'robot_state', joints: servo.joints, stateName: 'IDLE' });
  const result = results.find(message => message.type === 'skill.result');
  const execution = results.find(message => message.type === 'execution.request');
  assert(result, 'expected a final skill.result');
  assert(execution, 'expected an execution.request');
  assert.strictEqual(result.success, true);
  assert.strictEqual(result.requestId, execution.requestId);
  assert.strictEqual(result.simulated, false);
  bridge.shutdown();
}

console.log('PASS language upstream bridge smoke');
