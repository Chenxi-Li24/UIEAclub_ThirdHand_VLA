'use strict';

const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');

function parsePort(value, fallback) {
  const port = Number(value ?? fallback);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    throw new Error('VISION_PORT must be an integer within [0, 65535]');
  }
  return port;
}

function loadConfig(env = process.env) {
  return {
    root: ROOT,
    host: env.VISION_HOST || '127.0.0.1',
    port: parsePort(env.VISION_PORT, 3100),
    meituanHost: env.MEITUAN_VISION_HOST || '127.0.0.1',
    meituanPort: env.MEITUAN_VISION_PORT == null || env.MEITUAN_VISION_PORT === ''
      ? null : parsePort(env.MEITUAN_VISION_PORT, 1035),
    readyFile: env.THIRDHAND_READY_FILE ||
      path.join(ROOT, 'runtime/run/vision.ready'),
    python: env.VISION_PYTHON ||
      path.join(ROOT, 'local/runtimes/python/bin/python'),
    bridgeScript: env.VISION_BRIDGE_SCRIPT ||
      path.join(ROOT, 'services/vision/python/camera_bridge.py'),
    visionConfig: env.VISION_CONFIG ||
      path.join(ROOT, 'configs/vision.yaml'),
    handeye: env.THIRDHAND_VA_HANDEYE || null,
    robotUrdf: env.THIRDHAND_ROBOT_URDF || null,
    xvisioExecutable: env.XVISIO_STREAM_EXECUTABLE ||
      path.join(ROOT, 'runtime/build/xvisio/xvisio_rgbd_stream'),
    selectedTargetExportDir: env.SELECTED_TARGET_EXPORT_DIR ||
      path.join(ROOT, 'runtime/vision/selected-target-exports'),
    exportTimeoutMs: Number(env.SELECTED_TARGET_EXPORT_TIMEOUT_MS || 10000),
  };
}

module.exports = { ROOT, loadConfig };
