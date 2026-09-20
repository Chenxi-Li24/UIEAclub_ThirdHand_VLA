'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

const {
  StartouchProcessClient,
  runtimeConfigId,
} = require('../../../src/thirdhand_va/action/adapters/startouch_process_client');

const PROJECT_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = process.env.THIRDHAND_VA_PYTHON || process.env.PYTHON ||
  (process.platform === 'win32' ? 'python' : 'python3');
const BRIDGE = path.join(PROJECT_ROOT, 'native/startouch/startouch_bridge.py');
const RUNTIME_SETTINGS = Object.freeze({
  backend: 'simulate',
  can_interface: null,
  gripper_max_width_m: 0.080,
  lock_file: null,
  runtime_manifest_id: null,
  runtime_root: null,
  safety_config_sha256: null,
  safety_profile_id: null,
  source_manifest: null,
  state_period_ms: 100,
});

function onceMatching(emitter, eventName, predicate = () => true, timeoutMs = 3000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error(`timeout waiting for ${eventName}`));
    }, timeoutMs);
    function onEvent(event) {
      if (!predicate(event)) return;
      cleanup();
      resolve(event);
    }
    function cleanup() {
      clearTimeout(timer);
      emitter.off(eventName, onEvent);
    }
    emitter.on(eventName, onEvent);
  });
}

async function waitForState(client, timeoutMs = 3000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const state = client.getRobotState();
    if (state?.stateFresh === true) return state;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('timeout waiting for fresh robot state');
}

function simulatedClient(options = {}) {
  return new StartouchProcessClient({
    pythonExecutable: PYTHON,
    bridgePath: BRIDGE,
    bridgeArgs: ['--simulate', '--state-period-ms', '100'],
    runtimeSettings: RUNTIME_SETTINGS,
    presets: { home: [0, 0, 0, 0, 0, 0] },
    jointMaxSpeedsDegS: [300, 300, 300, 1000, 1000, 1000],
    speedScale: 0.05,
    ...options,
  });
}

test('process client completes strict handshake and exposes fresh flange state', async t => {
  const client = simulatedClient();
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');

  assert.equal(client.connect(), true);
  assert.deepEqual(await protocol, { type: 'protocol', ready: true, reason: null });
  const state = await waitForState(client);

  assert.equal(client.connected, true);
  assert.equal(client.protocolReady, true);
  assert.equal(client.stopProofMode, 'cleanup_ack_only');
  assert.equal(state.poseFrame, 'robot_flange');
  assert.equal(state.connected, true);
  assert.equal(state.stationary, true);
  assert.deepEqual(state.flangePositionM, [0.45, 0.0, 0.25]);
  assert.deepEqual(state.flangeEulerRad, [0.0, 0.0, 0.0]);
  assert.equal(state.gripperWidthM, 0.080);
});

test('process client accepts validated tracker idle velocity noise as stationary', () => {
  const client = simulatedClient({ nowNs: () => 2_000_000_000 });
  const state = client._normalizeState({
    pose_frame: 'robot_flange', connected: true, healthy: true, moving: false,
    flange_position_m: [0.257, 0, 0.037], flange_euler_rad: [0, 0, 0],
    joints_deg: [0, 0, 0, 0, 0, 0],
    velocities_deg_s: [0.11, 0.34, 0.11, 1.26, 0.42, -0.42],
    gripper_width_m: 0.080, state_sequence: 1,
    producer_monotonic_ns: 1_000_000_000,
  });

  assert.equal(state.stationary, true);
});

test('process client maps Action move fields and correlates measured completion', async t => {
  const client = simulatedClient();
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');
  client.connect();
  await protocol;
  await waitForState(client);
  const completion = onceMatching(
    client,
    'command_complete',
    event => event.request_id === 'move-node-1',
  );

  assert.equal(client.send({
    cmd: 'move_l',
    request_id: 'move-node-1',
    position: [0.40, 0.05, 0.18],
    euler: [0.0, 0.0, 0.0],
    time_sec: 3.334,
    source: 'test:node-move',
  }), true);

  assert.deepEqual(await completion, {
    type: 'command_complete',
    command: 'move_l',
    request_id: 'move-node-1',
    reached: true,
    actualFlangePositionM: [0.40, 0.05, 0.18],
    actualFlangeEulerRad: [0.0, 0.0, 0.0],
    actual_width_m: undefined,
    robot_healthy: true,
    stopped: false,
    depowered: false,
    applied_state_sequence: undefined,
    applied_producer_monotonic_ns: undefined,
  });
  assert.deepEqual((await waitForState(client)).flangePositionM, [0.40, 0.05, 0.18]);
});

test('named home preset is translated to move_joint and restored as preset completion', async t => {
  const client = simulatedClient();
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');
  client.connect();
  await protocol;
  await waitForState(client);
  const completion = onceMatching(
    client,
    'command_complete',
    event => event.request_id === 'home-node-1',
  );

  assert.equal(client.send({
    cmd: 'preset', name: 'home', request_id: 'home-node-1', source: 'grasp:return_home',
  }), true);
  const event = await completion;

  assert.equal(event.command, 'preset');
  assert.equal(event.request_id, 'home-node-1');
  assert.equal(event.reached, true);
  assert.deepEqual(event.actualJointsDeg, [0, 0, 0, 0, 0, 0]);
});

test('software stop reports correlated cleanup without claiming depower', async t => {
  const client = simulatedClient();
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');
  client.connect();
  await protocol;
  await waitForState(client);
  const completion = onceMatching(
    client,
    'command_complete',
    event => event.request_id === 'stop-node-1',
  );

  assert.equal(client.send({
    cmd: 'software_stop', request_id: 'stop-node-1', reason: 'test-stop',
  }), true);
  const event = await completion;

  assert.equal(event.command, 'software_stop');
  assert.equal(event.cleanupAcknowledged, true);
  assert.equal(event.cleanupConfirmationMode, 'simulation');
  assert.equal(event.controlReleased, true);
  assert.equal(event.depowerIndependentlyConfirmed, false);
  assert.equal(event.stopped, false);
  assert.equal(event.depowered, false);
  assert.equal(Number.isSafeInteger(event.applied_state_sequence), true);
  assert.equal(Number.isSafeInteger(event.applied_producer_monotonic_ns), true);
});

test('wrong bridge protocol is rejected before any command can be sent', async () => {
  const client = simulatedClient();
  const protocol = onceMatching(client, 'protocol');

  client._onMessage({
    type: 'bridge_ready',
    schema: 'thirdhand-startouch-bridge-v1',
    protocol_version: 'wrong-protocol',
  });

  assert.deepEqual(await protocol, {
    type: 'protocol', ready: false, reason: 'capability_handshake_invalid',
  });
  assert.equal(client.protocolReady, false);
  assert.equal(client.send({ cmd: 'get_state', request_id: 'must-not-send' }), false);
});

test('malformed bridge stdout becomes an explicit adapter error', async () => {
  const client = simulatedClient();
  const error = onceMatching(client, 'error');

  client._onStdout('{not-json}\n');

  assert.deepEqual(await error, {
    type: 'error', reason: 'robot_message_invalid', request_id: null,
  });
});

test('unexpected child exit never becomes a successful stop', async () => {
  const client = simulatedClient();
  const error = onceMatching(client, 'error');

  client._onClose(7, null);

  assert.deepEqual(await error, {
    type: 'error', reason: 'robot_process_exited', request_id: null, stderr: '',
  });
  assert.equal(client.connected, false);
  assert.equal(client.protocolReady, false);
});

test('a previously valid state becomes fail-closed after its age limit', async t => {
  let nowNs = 1_000_000_000;
  const client = simulatedClient({ nowNs: () => nowNs, maxStateAgeMs: 250 });
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');
  client.connect();
  await protocol;
  const state = await waitForState(client);
  assert.equal(state.stateFresh, true);

  nowNs += 251_000_000;

  assert.equal(client.getRobotState().stateFresh, false);
});

test('a second motion is rejected while the first command is in flight', async t => {
  const client = simulatedClient();
  t.after(() => client.shutdown());
  const protocol = onceMatching(client, 'protocol');
  client.connect();
  await protocol;
  await waitForState(client);
  const completion = onceMatching(
    client, 'command_complete', event => event.request_id === 'first-motion',
  );

  assert.equal(client.send({
    cmd: 'move_l', request_id: 'first-motion',
    position: [0.44, 0, 0.24], euler: [0, 0, 0], time_sec: 1,
  }), true);
  assert.equal(client.send({
    cmd: 'move_l', request_id: 'second-motion',
    position: [0.43, 0, 0.24], euler: [0, 0, 0], time_sec: 1,
  }), false);
  assert.equal((await completion).reached, true);
});

test('stop without cleanup acknowledgement is normalized as unconfirmed', async () => {
  const client = simulatedClient();
  client.stopInFlight = {
    requestId: 'unproved-stop',
    publicCommand: 'software_stop',
    wireCommand: 'software_stop',
  };
  const completion = onceMatching(client, 'command_complete');

  client._onCommandEvent({
    type: 'command_complete', command: 'software_stop',
    request_id: 'unproved-stop', cleanup_acknowledged: false,
    cleanup_confirmation_mode: 'vendor_cleanup_returned',
    depower_independently_confirmed: false, control_released: true,
  });

  const event = await completion;
  assert.equal(event.cleanupAcknowledged, false);
  assert.equal(event.stopped, false);
  assert.equal(event.depowered, false);
  assert.equal(event.applied_state_sequence, undefined);
  assert.equal(event.applied_producer_monotonic_ns, undefined);
});

test('runtime config content ID is canonical and changes with one setting', () => {
  assert.equal(
    runtimeConfigId(RUNTIME_SETTINGS),
    'sha256:1ac663b7a7c677076ff7073ca37dbbdbf1f93036c2f8fa2139b8c6a57cde7191',
  );
  assert.notEqual(
    runtimeConfigId({ ...RUNTIME_SETTINGS, state_period_ms: 101 }),
    runtimeConfigId(RUNTIME_SETTINGS),
  );
});

test('standalone protocol debugger completes a simulated move gripper and stop cycle', () => {
  const result = spawnSync(
    process.execPath,
    ['scripts/action/debug_startouch_protocol.js', '--simulate'],
    { cwd: PROJECT_ROOT, encoding: 'utf8', timeout: 10000 },
  );

  assert.equal(result.status, 0, result.stderr);
  const summary = JSON.parse(result.stdout.trim().split('\n').at(-1));
  assert.deepEqual(summary, {
    cleanup_acknowledged: true,
    depower_independently_confirmed: false,
    hardware_connected: false,
    ok: true,
  });
});
