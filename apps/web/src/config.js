'use strict';

const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');
const LANGUAGE_JOINT_LIMITS_DEG = Object.freeze([
  [-162, 162],
  [-12, 201],
  [-183, 0],
  [-98, 98],
  [-98, 98],
  [-164, 164],
]);
const LANGUAGE_JOINT_MAX_SPEEDS_DEG_S = Object.freeze([300, 300, 300, 1000, 1000, 1000]);

function portFrom(env, name, fallback) {
  const value = Number(env[name] ?? fallback);
  if (!Number.isInteger(value) || value < 0 || value > 65535) {
    throw new Error(`${name} must be an integer within [0, 65535]`);
  }
  return value;
}

function loadConfig(env = process.env) {
  return {
    host: env.WEB_HOST || '0.0.0.0',
    port: portFrom(env, 'WEB_PORT', 9983),
    publicDir: env.WEB_PUBLIC_DIR || path.join(ROOT, 'apps', 'web', 'public'),
    assetsDir: env.ROBOT_ASSETS_DIR || path.join(ROOT, 'assets', 'robot'),
    readyFile: env.THIRDHAND_READY_FILE || path.join(ROOT, 'runtime', 'run', 'web.ready'),
    robotWsUrl: env.ROBOT_WS_URL || 'ws://127.0.0.1:3000/ws',
    voiceWsUrl: env.VOICE_WS_URL || 'ws://127.0.0.1:3004/v1/voice',
    orchestratorWsUrl: env.ORCHESTRATOR_WS_URL || 'ws://127.0.0.1:3200/plan',
    visionHttpUrl: env.VISION_HTTP_URL || 'http://127.0.0.1:3100',
    visionWsUrl: env.VISION_WS_URL || 'ws://127.0.0.1:3100/ws',
    language: {
      realControlEnabled: env.LANGUAGE_REAL_CONTROL === '1',
      directionalEnabled: env.DIRECTIONAL_CONTROL_ENABLED === '1',
      directionalRealControlEnabled: env.DIRECTIONAL_REAL_CONTROL === '1',
      stateMaxAgeMs: 500,
      maxDeltaDeg: null,
      speedScale: 0.05,
      jointToleranceDeg: 1,
      gripperOpenTarget: Number(env.LANGUAGE_GRIPPER_OPEN_TARGET || 1),
      gripperCloseTarget: Number(env.LANGUAGE_GRIPPER_CLOSE_TARGET || 0),
      gripperTimeoutMs: Number(env.LANGUAGE_GRIPPER_TIMEOUT_MS || 5000),
      minMoveTimeSec: 0.5,
      maxMoveTimeSec: 30,
      jointLimitsDeg: LANGUAGE_JOINT_LIMITS_DEG,
      jointMaxSpeedsDegS: LANGUAGE_JOINT_MAX_SPEEDS_DEG_S,
    },
  };
}

module.exports = { ROOT, loadConfig };
