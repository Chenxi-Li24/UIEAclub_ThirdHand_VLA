'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');

function numberFrom(env, name, fallback, minimum, maximum) {
  const value = Number(env[name] ?? fallback);
  if (!Number.isFinite(value)) throw new Error(`${name} must be numeric`);
  return Math.max(minimum, Math.min(maximum, value));
}

function boolFrom(env, name, fallback) {
  if (!(name in env)) return fallback;
  return env[name] === '1';
}

function loadConfig(env = process.env) {
  const localPython = path.join(ROOT, 'local', 'runtimes', 'python', 'bin', 'python');
  const sdkPath = env.STARTOUCH_SDK_PATH
    || path.join(ROOT, 'local', 'sdk', 'startouch');
  const generatedModulePath = path.join(
    ROOT, 'local', 'generated', 'startouch-python',
  );
  return {
    host: env.ROBOT_HOST || '127.0.0.1',
    port: numberFrom(env, 'ROBOT_PORT', 3000, 0, 65535),
    readyFile: env.THIRDHAND_READY_FILE || path.join(ROOT, 'runtime', 'run', 'robot.ready'),
    robot: {
      python: env.STARTOUCH_PYTHON || (fs.existsSync(localPython) ? localPython : 'python3'),
      sdkPath,
      modulePath: env.STARTOUCH_MODULE_PATH
        || (fs.existsSync(generatedModulePath)
          ? generatedModulePath
          : path.join(sdkPath, 'interface_py')),
      canInterface: env.STARTOUCH_CAN_INTERFACE || 'can0',
      gripper: boolFrom(env, 'STARTOUCH_GRIPPER', true),
      requireCanRx: boolFrom(env, 'STARTOUCH_REQUIRE_CAN_RX', true),
      canRxStaleSec: numberFrom(env, 'STARTOUCH_CAN_RX_STALE_SEC', 1, 0.25, 30),
      simulate: boolFrom(env, 'STARTOUCH_SIMULATE', false),
      dryRun: boolFrom(env, 'STARTOUCH_DRY_RUN', false),
      pollIntervalMs: numberFrom(env, 'STARTOUCH_POLL_INTERVAL_MS', 100, 20, 5000),
      jointLogIntervalMs: numberFrom(env, 'STARTOUCH_JOINT_LOG_INTERVAL_MS', 1000, 50, 60000),
      initSettleSec: numberFrom(env, 'STARTOUCH_INIT_SETTLE_SEC', 2, 0, 30),
      initSampleCount: numberFrom(env, 'STARTOUCH_INIT_SAMPLE_COUNT', 3, 2, 20),
      initMaxDriftDeg: numberFrom(env, 'STARTOUCH_INIT_MAX_DRIFT_DEG', 2, 0.1, 20),
      speedScale: numberFrom(env, 'STARTOUCH_SPEED_SCALE', 0.05, 0.01, 1),
      minMoveTimeSec: numberFrom(env, 'STARTOUCH_MIN_MOVE_TIME_SEC', 0.5, 0.05, 30),
      maxMoveTimeSec: numberFrom(env, 'STARTOUCH_MAX_MOVE_TIME_SEC', 30, 0.1, 120),
    },
  };
}

module.exports = { ROOT, loadConfig };
