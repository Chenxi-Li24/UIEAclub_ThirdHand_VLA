#!/usr/bin/env node
'use strict';

const path = require('node:path');

const { StartouchProcessClient } = require(
  '../../src/thirdhand_va/action/adapters/startouch_process_client'
);

const PROJECT_ROOT = path.resolve(__dirname, '../..');
const PYTHON = process.env.THIRDHAND_VA_PYTHON ||
  '/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python';

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
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const state = client.getRobotState();
    if (state?.stateFresh === true) return state;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('fresh simulated state unavailable');
}

async function sendAndWait(client, command) {
  const completion = onceMatching(
    client,
    'command_complete',
    event => event.request_id === command.request_id,
  );
  if (client.send(command) !== true) throw new Error(`${command.cmd} rejected`);
  const event = await completion;
  console.log(JSON.stringify(event));
  return event;
}

async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 1 || argv[0] !== '--simulate') {
    console.error('usage: node scripts/action/debug_startouch_protocol.js --simulate');
    return 2;
  }
  const runtimeSettings = {
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
  };
  const client = new StartouchProcessClient({
    pythonExecutable: PYTHON,
    bridgePath: path.join(PROJECT_ROOT, 'native/startouch/startouch_bridge.py'),
    bridgeArgs: ['--simulate', '--state-period-ms', '100'],
    runtimeSettings,
    presets: { home: [0, 0, 0, 0, 0, 0] },
    jointMaxSpeedsDegS: [300, 300, 300, 1000, 1000, 1000],
    speedScale: 0.05,
  });
  const errors = [];
  client.on('error', event => errors.push(event));
  try {
    console.log(JSON.stringify({
      backend: 'simulate',
      bridge_schema: 'thirdhand-startouch-bridge-v1',
      hardware_connected: false,
      robot_control_enabled: false,
    }));
    const protocol = onceMatching(client, 'protocol', event => event.ready === true);
    if (client.connect() !== true) throw new Error('simulated bridge spawn rejected');
    console.log(JSON.stringify(await protocol));
    console.log(JSON.stringify(await waitForState(client)));
    const move = await sendAndWait(client, {
      cmd: 'move_l',
      request_id: 'debug-move',
      position: [0.44, 0.0, 0.24],
      euler: [0.0, 0.0, 0.0],
      time_sec: 1.0,
      source: 'debug:simulated-move',
    });
    const close = await sendAndWait(client, {
      cmd: 'gripper', request_id: 'debug-close', position: 0.5,
      source: 'debug:simulated-close',
    });
    const open = await sendAndWait(client, {
      cmd: 'gripper', request_id: 'debug-open', position: 1.0,
      source: 'debug:simulated-open',
    });
    const stop = await sendAndWait(client, {
      cmd: 'software_stop', request_id: 'debug-stop', reason: 'debug_complete',
      source: 'debug:simulated-stop',
    });
    const closed = onceMatching(
      client, 'connection', event => event.connected === false,
    );
    client.shutdown();
    await closed;
    const ok = move.reached === true && close.actual_width_m === 0.040 &&
      open.actual_width_m === 0.080 && stop.cleanupAcknowledged === true &&
      stop.depowerIndependentlyConfirmed === false && errors.length === 0;
    console.log(JSON.stringify({
      cleanup_acknowledged: stop.cleanupAcknowledged === true,
      depower_independently_confirmed: stop.depowerIndependentlyConfirmed,
      hardware_connected: false,
      ok,
    }));
    return ok ? 0 : 1;
  } catch (error) {
    client.shutdown();
    console.error(error instanceof Error ? error.message : String(error));
    return 1;
  }
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; });
}

module.exports = { main };
