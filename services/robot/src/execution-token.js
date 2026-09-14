'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');

const TOKEN_PATTERN = /^[0-9a-f]{64}$/;

function validateToken(token) {
  if (!TOKEN_PATTERN.test(token)) throw new Error('Robot execution token must be 64 lowercase hexadecimal characters');
  return token;
}

function loadExecutionToken({ token, tokenFile } = {}) {
  if (token !== undefined) return { available: true, token: validateToken(String(token)), reason: null };
  if (!tokenFile) return { available: false, token: null, reason: 'execution_token_not_configured' };
  const stat = fs.statSync(tokenFile);
  if (process.platform !== 'win32' && (stat.mode & 0o077) !== 0) {
    throw new Error('Robot execution token file permissions must be 0600 or stricter');
  }
  return { available: true, token: validateToken(fs.readFileSync(tokenFile, 'utf8').trim()), reason: null };
}

function tokenMatches(expected, supplied) {
  if (typeof supplied !== 'string' || supplied.length !== expected.length) return false;
  return crypto.timingSafeEqual(Buffer.from(expected, 'ascii'), Buffer.from(supplied, 'ascii'));
}

module.exports = { TOKEN_PATTERN, loadExecutionToken, tokenMatches, validateToken };
