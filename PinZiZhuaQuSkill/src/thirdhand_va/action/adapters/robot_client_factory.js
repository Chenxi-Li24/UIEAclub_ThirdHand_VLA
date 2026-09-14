'use strict';

const path = require('node:path');

const { StartouchProcessClient } = require('./startouch_process_client');
const { RobotWebSocketClient } = require('./robot_ws_client');

const REAL_ACK = 'I_ACCEPT_SUPERVISED_ROBOT_MOTION';
const STATE_PERIOD_MS = 100;

function createRobotClient(config, dependencies = {}) {
  const robot = config?.robot;
  if (!robot || typeof robot !== 'object') {
    throw new TypeError('robot_backend_config_missing');
  }
  if (robot.backend === 'startouch_process') {
    if (dependencies.realAuthorization !== REAL_ACK) {
      throw new TypeError('real_robot_authorization_missing');
    }
    const runtimeSettings = {
      backend: 'startouch_sdk',
      can_interface: robot.can_interface,
      gripper_max_width_m: config.gripper.physical_max_width_m,
      lock_file: robot.lock_file,
      runtime_manifest_id: robot.runtime_manifest_id,
      runtime_root: robot.runtime_root,
      safety_config_sha256: robot.safety_config_sha256,
      safety_profile_id: robot.safety_profile_id,
      source_manifest: robot.source_manifest,
      state_period_ms: STATE_PERIOD_MS,
    };
    return new StartouchProcessClient({
      pythonExecutable: robot.python_executable,
      bridgePath: robot.bridge_path,
      bridgeArgs: [
        '--real',
        '--state-period-ms', String(STATE_PERIOD_MS),
        '--runtime-root', robot.runtime_root,
        '--source-manifest', robot.source_manifest,
        '--expected-safety-config-sha256', robot.safety_config_sha256,
        '--can-interface', robot.can_interface,
        '--lock-file', robot.lock_file,
        '--gripper-max-width-m', String(config.gripper.physical_max_width_m),
        '--allow-real', REAL_ACK,
      ],
      runtimeSettings,
      childEnvironment: {
        LD_LIBRARY_PATH: [
          path.join(robot.runtime_root, 'src'),
          process.env.LD_LIBRARY_PATH,
        ].filter(Boolean).join(path.delimiter),
      },
      presets: robot.presets,
      jointMaxSpeedsDegS: robot.joint_max_speeds_deg_s,
      speedScale: robot.speed_scale,
      ...(dependencies.spawnImpl ? { spawnImpl: dependencies.spawnImpl } : {}),
      ...(dependencies.nowNs ? { nowNs: dependencies.nowNs } : {}),
    });
  }
  if (robot.backend === 'websocket') {
    return new RobotWebSocketClient({
      WebSocketImpl: dependencies.WebSocketImpl,
      url: robot.ws_url,
      gripperMaxWidthM: config.gripper.physical_max_width_m,
      ...(dependencies.nowNs ? { nowNs: dependencies.nowNs } : {}),
    });
  }
  throw new TypeError('robot_backend_unsupported');
}

module.exports = { createRobotClient, REAL_ACK, STATE_PERIOD_MS };
