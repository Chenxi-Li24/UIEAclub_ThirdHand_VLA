'use strict';

const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');

function loadConfig(env = process.env) {
  const port = Number(env.ORCHESTRATOR_PORT ?? 3200);
  if (!Number.isInteger(port) || port < 0 || port > 65535) throw new Error('ORCHESTRATOR_PORT must be within [0, 65535]');
  return {
    host: env.ORCHESTRATOR_HOST || '127.0.0.1',
    port,
    readyFile: env.THIRDHAND_READY_FILE || path.join(ROOT, 'runtime', 'run', 'orchestrator.ready'),
    robotHealthUrl: env.ROBOT_HTTP_URL || 'http://127.0.0.1:3000',
    robotExecutionWsUrl: env.ROBOT_EXECUTION_WS_URL || 'ws://127.0.0.1:3000/execution',
    robotExecutionTokenFile: env.ROBOT_EXECUTION_TOKEN_FILE || null,
  };
}

module.exports = { ROOT, loadConfig };
