'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { loadActionConfig } = require('../../../src/thirdhand_va/action/config');
const {
  createRobotClient,
} = require('../../../src/thirdhand_va/action/adapters/robot_client_factory');

const ACK = 'I_ACCEPT_SUPERVISED_ROBOT_MOTION';

class FakeWebSocket {}

test('factory selects only the explicitly configured robot backend', () => {
  const config = loadActionConfig('configs/action.yaml');
  const processClient = createRobotClient(config, {
    realAuthorization: ACK,
    spawnImpl() { throw new Error('factory must not spawn during construction'); },
  });
  const websocketClient = createRobotClient({
    ...config,
    robot: { ...config.robot, backend: 'websocket' },
  }, { WebSocketImpl: FakeWebSocket });

  assert.equal(processClient.constructor.name, 'StartouchProcessClient');
  assert.equal(processClient.stopProofMode, 'cleanup_ack_only');
  assert.equal(processClient.bridgeArgs.includes('--real'), true);
  assert.equal(processClient.bridgeArgs.includes('--simulate'), false);
  assert.equal(processClient.bridgeArgs.includes('--sdk-path'), false);
  assert.equal(processClient.runtimeSettings.sdk_path, undefined);
  assert.equal(processClient.runtimeSettings.runtime_root, config.robot.runtime_root);
  assert.equal(processClient.runtimeSettings.runtime_manifest_id,
    config.robot.runtime_manifest_id);
  assert.equal(processClient.runtimeSettings.safety_config_sha256,
    config.robot.safety_config_sha256);
  assert.equal(processClient.runtimeSettings.lock_file, config.robot.lock_file);
  assert.equal(processClient.childEnvironment.LD_LIBRARY_PATH.split(':')[0],
    `${config.robot.runtime_root}/src`);
  assert.equal(websocketClient.constructor.name, 'RobotWebSocketClient');
  assert.equal(websocketClient.stopProofMode, 'fresh_state_boundary');
});

test('factory rejects missing real authorization and unknown backend without fallback', () => {
  const config = loadActionConfig('configs/action.yaml');
  assert.throws(
    () => createRobotClient(config, {}),
    /real_robot_authorization_missing/
  );
  assert.throws(
    () => createRobotClient({
      ...config, robot: { ...config.robot, backend: 'automatic' },
    }, { realAuthorization: ACK, WebSocketImpl: FakeWebSocket }),
    /robot_backend_unsupported/
  );
});

test('real process handshake binds the safety runtime and inbound CAN identity', () => {
  const config = loadActionConfig('configs/action.yaml');
  const client = createRobotClient(config, {
    realAuthorization: ACK,
    spawnImpl() { throw new Error('must not spawn'); },
  });
  const ready = {
    type: 'bridge_ready',
    schema: 'thirdhand-startouch-bridge-v1',
    protocol_version: 'thirdhand-robot-lowlevel-v1',
    commands: [
      'connect', 'disconnect', 'get_state', 'gripper',
      'move_joint', 'move_l', 'software_stop',
    ],
    correlated_completions: true,
    pose_frame: 'robot_flange',
    software_stop_ack: true,
    stop_proof_mode: 'cleanup_ack_only',
    state_units: {
      gripper: 'm', joint_velocity: 'deg/s', joints: 'deg',
      orientation: 'rad', position: 'm',
    },
    state_stream: {
      producer_monotonic_ns: 'uint53', sequence: 'uint53',
      strictly_increasing: true,
    },
    bridge_content_id: client.expectedBridgeContentId,
    runtime_config_id: client.expectedRuntimeConfigId,
    runtime_identity: {
      runtime_manifest_id: config.robot.runtime_manifest_id,
      safety_config_sha256: config.robot.safety_config_sha256,
      safety_profile_id: config.robot.safety_profile_id,
      startup_feedback_ids: [0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17],
    },
  };

  assert.equal(client._validReady(ready), true);
  assert.equal(client._validReady({
    ...ready,
    runtime_identity: {
      ...ready.runtime_identity, startup_feedback_ids: [0x11, 0x12],
    },
  }), false);
  assert.equal(client._validReady({
    ...ready,
    runtime_identity: {
      ...ready.runtime_identity, safety_config_sha256: 'f'.repeat(64),
    },
  }), false);
});
