'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const EXECUTION_TOKEN_NAME = 'robot-execution.token';
const TOKEN_PATTERN = /^[0-9a-f]{64}$/;

function executionTokenPath(runtimeDir) {
  return path.join(path.resolve(runtimeDir), 'run', EXECUTION_TOKEN_NAME);
}

function validateExistingToken(tokenPath) {
  const stat = fs.statSync(tokenPath);
  if (!stat.isFile()) throw new Error('execution token path is not a file');
  if (process.platform !== 'win32' && (stat.mode & 0o077) !== 0) {
    throw new Error('execution token permissions must be 0600 or stricter');
  }
  const value = fs.readFileSync(tokenPath, 'utf8').trim();
  if (!TOKEN_PATTERN.test(value)) throw new Error('execution token has invalid format');
}

function prepareExecutionToken({ runtimeDir }) {
  const tokenPath = executionTokenPath(runtimeDir);
  fs.mkdirSync(path.dirname(tokenPath), { recursive: true });
  if (fs.existsSync(tokenPath)) {
    validateExistingToken(tokenPath);
    return { path: tokenPath, created: false };
  }

  const temporary = path.join(
    path.dirname(tokenPath),
    `.${EXECUTION_TOKEN_NAME}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`,
  );
  const fd = fs.openSync(temporary, 'wx', 0o600);
  try {
    fs.writeFileSync(fd, `${crypto.randomBytes(32).toString('hex')}\n`, 'utf8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.chmodSync(temporary, 0o600);
  try {
    fs.renameSync(temporary, tokenPath);
  } catch (error) {
    try { fs.unlinkSync(temporary); } catch (unlinkError) {
      if (unlinkError.code !== 'ENOENT') throw unlinkError;
    }
    throw error;
  }
  return { path: tokenPath, created: true };
}

function removeExecutionToken({ runtimeDir }) {
  const tokenPath = executionTokenPath(runtimeDir);
  try {
    fs.unlinkSync(tokenPath);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

module.exports = {
  EXECUTION_TOKEN_NAME,
  executionTokenPath,
  prepareExecutionToken,
  removeExecutionToken,
};
