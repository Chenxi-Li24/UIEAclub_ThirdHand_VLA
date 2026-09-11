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
    readyFile: env.THIRDHAND_READY_FILE ||
      path.join(ROOT, 'runtime/run/vision.ready'),
    python: env.VISION_PYTHON ||
      path.join(ROOT, 'local/runtimes/python/bin/python'),
    bridgeScript: env.VISION_BRIDGE_SCRIPT ||
      path.join(ROOT, 'services/vision/python/camera_bridge.py'),
    visionConfig: env.VISION_CONFIG ||
      path.join(ROOT, 'configs/vision.yaml'),
    xvisioExecutable: env.XVISIO_STREAM_EXECUTABLE ||
      path.join(ROOT, 'runtime/build/xvisio/xvisio_rgbd_stream'),
  };
}

module.exports = { ROOT, loadConfig };
