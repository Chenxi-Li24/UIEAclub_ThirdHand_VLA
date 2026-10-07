'use strict';

const path = require('node:path');
const fs = require('node:fs');

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
  if (env.DUMMY_TELEMETRY_PORT != null && Number(env.DUMMY_TELEMETRY_PORT) === 0) {
    throw new Error('DUMMY_TELEMETRY_PORT must not be zero for managed Dummy');
  }
  const resourceRoot = env.DUMMY_RESOURCE_ROOT || ROOT;
  const dummyPython = path.join(resourceRoot, 'local/runtimes/dummy-python/bin/python');
  const speech = new URL(env.VOICE_WS_URL || 'ws://127.0.0.1:3004/v1/voice');
  speech.pathname = '/v1/transcripts';
  speech.search = '';
  return {
    host: env.WEB_HOST || '0.0.0.0',
    port: portFrom(env, 'WEB_PORT', 9983),
    publicDir: env.WEB_PUBLIC_DIR || path.join(ROOT, 'apps', 'web', 'public'),
    assetsDir: env.ROBOT_ASSETS_DIR || path.join(ROOT, 'assets', 'robot'),
    readyFile: env.THIRDHAND_READY_FILE || path.join(ROOT, 'runtime', 'run', 'web.ready'),
    robotWsUrl: env.ROBOT_WS_URL || 'ws://127.0.0.1:3000/ws',
    robotExecutionWsUrl: env.ROBOT_EXECUTION_WS_URL || 'ws://127.0.0.1:3000/execution',
    robotExecutionTokenFile: env.ROBOT_EXECUTION_TOKEN_FILE || path.join(ROOT, 'runtime', 'run', 'robot-execution.token'),
    activeDepthMountFile: env.ACTIVE_DEPTH_MOUNT_FILE || path.join(
      ROOT, 'skills', 'manipulation', 'bottlegrasp', 'configs', 'calibration',
      'lumos-handeye.pending.json',
    ),
    voiceWsUrl: env.VOICE_WS_URL || 'ws://127.0.0.1:3004/v1/voice',
    visionHttpUrl: env.VISION_HTTP_URL || 'http://127.0.0.1:3100',
    visionWsUrl: env.VISION_WS_URL || 'ws://127.0.0.1:3100/ws',
    dummy: {
      root: ROOT,
      python: env.DUMMY_PYTHON || (fs.existsSync(dummyPython) ? dummyPython
        : path.join(resourceRoot, 'local/runtimes/vision-python/bin/python')),
      entry: path.join(ROOT, 'apps/dummy/apps/run_head_body_follow.py'),
      urdf: env.DUMMY_URDF_PATH || path.join(resourceRoot, 'assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf'),
      faceModel: env.DUMMY_FACE_MODEL || path.join(resourceRoot, 'apps/dummy/models/blaze_face_short_range.tflite'),
      yoloModel: env.DUMMY_YOLO_MODEL || path.join(resourceRoot, 'local/models/vision/yolov8n.pt'),
      speechWs: env.DUMMY_SPEECH_WS || speech.href,
      telemetryPort: portFrom(env, 'DUMMY_TELEMETRY_PORT', 31024),
      logFile: path.join(ROOT, 'runtime/logs/dummy-web.log'),
    },
    language: {
      realControlEnabled: env.LANGUAGE_REAL_CONTROL === '1',
      visionHttpUrl: env.VISION_HTTP_URL || 'http://127.0.0.1:3100',
      vaHttpUrl: env.VA_HTTP_URL || 'http://127.0.0.1:8766',
      directionalEnabled: env.DIRECTIONAL_CONTROL_ENABLED === '1',
      directionalRealControlEnabled: env.DIRECTIONAL_REAL_CONTROL === '1',
      cameraMountFile: env.CAMERA_X_MOUNT_FILE || path.join(
        ROOT, 'skills', 'manipulation', 'bottlegrasp', 'configs', 'calibration',
        'lumos-handeye.pending.json',
      ),
      cameraDirectionValidationFile: env.CAMERA_X_VALIDATION_FILE || path.join(
        ROOT, 'runtime', 'run', 'camera-x-direction-validated.json',
      ),
      cameraProbeEnabled: env.CAMERA_X_PROBE_ENABLED === '1',
      cameraRealControlEnabled: env.CAMERA_X_REAL_CONTROL === '1',
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
