'use strict';

const { spawn } = require('node:child_process');

const RESULT_SCHEMAS = new Set([
  'thirdhand-tcp-pivot-solve-v1',
  'thirdhand-tcp-pivot-validation-v1',
  'thirdhand-grasp-tcp-derived-v1',
]);

function codedError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function finiteJson(value) {
  if (typeof value === 'number') return Number.isFinite(value);
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (Array.isArray(value)) return value.every(finiteJson);
  if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) {
    return false;
  }
  return Object.values(value).every(finiteJson);
}

function runTcpSolver({
  python,
  script,
  request,
  timeoutMs = 5000,
  maximumOutputBytes = 1024 * 1024,
}) {
  if (typeof python !== 'string' || !python || typeof script !== 'string' || !script
      || !Number.isSafeInteger(timeoutMs) || timeoutMs <= 0
      || !Number.isSafeInteger(maximumOutputBytes) || maximumOutputBytes <= 0) {
    return Promise.reject(codedError('solver_configuration_invalid'));
  }
  let requestBytes;
  try { requestBytes = Buffer.from(JSON.stringify(request)); }
  catch { return Promise.reject(codedError('solver_request_invalid')); }

  return new Promise((resolve, reject) => {
    const child = spawn(python, [script], { stdio: ['pipe', 'pipe', 'pipe'] });
    const stdout = [];
    let outputBytes = 0;
    let settled = false;
    const settle = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      callback(value);
    };
    const failAndKill = code => {
      child.kill('SIGKILL');
      settle(reject, codedError(code));
    };
    const timer = setTimeout(() => failAndKill('solver_timeout'), timeoutMs);
    timer.unref?.();

    child.once('error', () => settle(reject, codedError('solver_failed')));
    child.stdout.on('data', chunk => {
      if (settled) return;
      outputBytes += chunk.length;
      if (outputBytes > maximumOutputBytes) {
        failAndKill('solver_output_too_large');
        return;
      }
      stdout.push(chunk);
    });
    child.stderr.on('data', chunk => {
      if (settled) return;
      outputBytes += chunk.length;
      if (outputBytes > maximumOutputBytes) failAndKill('solver_output_too_large');
    });
    child.once('close', code => {
      if (settled) return;
      if (code !== 0) {
        settle(reject, codedError('solver_failed'));
        return;
      }
      let response;
      try { response = JSON.parse(Buffer.concat(stdout).toString('utf8')); }
      catch {
        settle(reject, codedError('solver_response_invalid'));
        return;
      }
      if (!finiteJson(response) || !RESULT_SCHEMAS.has(response.schema)) {
        settle(reject, codedError('solver_response_invalid'));
        return;
      }
      settle(resolve, response);
    });
    child.stdin.once('error', () => settle(reject, codedError('solver_failed')));
    child.stdin.end(requestBytes);
  });
}

module.exports = { runTcpSolver };
