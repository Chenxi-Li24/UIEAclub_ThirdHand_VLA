/**
 * ThirdHand Web Control - Startouch configuration.
 */
const os = require('os');
const path = require('path');

const simulate = process.env.STARTOUCH_SIMULATE === '1';
const requestedSpeedScale = Number(process.env.STARTOUCH_SPEED_SCALE || 0.05);
const speedScale = Number.isFinite(requestedSpeedScale)
  ? Math.max(0.01, Math.min(1, requestedSpeedScale))
  : 0.05;
const defaultArmRoot = path.join(os.homedir(), 'arm');

module.exports = {
  web: {
    host: process.env.WEB_HOST || '0.0.0.0',
    port: Number(process.env.WEB_PORT || 3000),
  },

  robot: {
    python: process.env.STARTOUCH_PYTHON ||
      (simulate
        ? 'python3'
        : path.join(os.homedir(), 'miniconda3', 'envs', 'LumosTouch', 'bin', 'python')),
    sdkPath: process.env.STARTOUCH_SDK_PATH || path.join(defaultArmRoot, 'startouch_sdk'),
    canInterface: process.env.STARTOUCH_CAN_INTERFACE || 'can0',
    gripper: process.env.STARTOUCH_GRIPPER !== '0',
    requireCanRx: process.env.STARTOUCH_REQUIRE_CAN_RX !== '0',
    canRxStaleSec: Number(process.env.STARTOUCH_CAN_RX_STALE_SEC || 1),
    simulate,
    dryRun: process.env.STARTOUCH_DRY_RUN === '1',
    pollIntervalMs: Number(process.env.STARTOUCH_POLL_INTERVAL_MS || 100),
    jointLogIntervalMs: Number(process.env.STARTOUCH_JOINT_LOG_INTERVAL_MS || 100),
    initSettleSec: Number(process.env.STARTOUCH_INIT_SETTLE_SEC || 2),
    initSampleCount: Number(process.env.STARTOUCH_INIT_SAMPLE_COUNT || 3),
    initMaxDriftDeg: Number(process.env.STARTOUCH_INIT_MAX_DRIFT_DEG || 2),
    speedScale,
    minMoveTimeSec: Number(process.env.STARTOUCH_MIN_MOVE_TIME_SEC || 0.5),
    maxMoveTimeSec: Number(process.env.STARTOUCH_MAX_MOVE_TIME_SEC || 30),
  },

  jointLimitsDeg: [
    [-162, 162],
    [-12, 201],
    [-183, 0],
    [-98, 98],
    [-98, 98],
    [-164, 164],
  ],

  jointMaxSpeedsDegS: [300, 300, 300, 1000, 1000, 1000],

  presets: {
    home: [0, 0, 0, 0, 0, 0],
  },

  model: {
    name: 'Startouch FastTouchV3',
    source: 'models/startouch-v3/FastTouchV3.SLDASM.urdf',
  },
};
