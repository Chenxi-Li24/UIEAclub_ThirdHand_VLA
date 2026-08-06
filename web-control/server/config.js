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

  camera: {
    enabled: process.env.CAMERA_ENABLED !== '0',
    python: process.env.CAMERA_PYTHON ||
      path.join(os.homedir(), 'miniconda3', 'envs', 'thirdhand-remind3d', 'bin', 'python'),
    onlineEnabled: process.env.VISION_ONLINE_ENABLED === '1',
    visionConfig: process.env.VISION_CONFIG ||
      path.resolve(__dirname, '../../configs/vision/remind3d.yaml'),
    activeViewConfig: process.env.ACTIVE_VIEW_CONFIG ||
      path.resolve(__dirname, '../../configs/vision/active_view.yaml'),
    activeViewEvidenceDir: process.env.ACTIVE_VIEW_EVIDENCE_DIR ||
      path.resolve(__dirname, '../../data/calibration/active-view'),
    activeViewCameraEvidence: process.env.ACTIVE_VIEW_CAMERA_EVIDENCE || '',
    activeViewTableEvidence: process.env.ACTIVE_VIEW_TABLE_EVIDENCE || '',
    activeViewCatalog: process.env.ACTIVE_VIEW_CATALOG || '',
    lumosSnapshotUrl: process.env.LUMOS_SNAPSHOT_URL ||
      'http://127.0.0.1:3001/frame.jpg',
    yoloModel: process.env.CAMERA_YOLO_MODEL || path.join(__dirname, 'yolov8n.pt'),
    calibrationFile: process.env.CAMERA_CALIB_FILE ||
      path.join(os.homedir(), 'calibration', 'd435_handeye_result.json'),
    detectionInterval: Number(process.env.CAMERA_DETECT_INTERVAL || 10),
    jpegQuality: Number(process.env.CAMERA_JPEG_QUALITY || 70),
    deskZ: Number(process.env.CAMERA_DESK_Z || 0.0),
    safeZ: Number(process.env.CAMERA_SAFE_Z || 0.12),
  },

  visionSafety: {
    // This release has no validated task checkpoint or calibration chain.
    robotExecutionEnabled: false,
  },
};
