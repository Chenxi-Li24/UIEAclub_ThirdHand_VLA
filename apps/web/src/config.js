'use strict';

const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');

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
  };
}

module.exports = { ROOT, loadConfig };
