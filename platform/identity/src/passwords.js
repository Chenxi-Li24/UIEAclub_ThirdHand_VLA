'use strict';
const argon2 = require('argon2');
const { identityError } = require('./errors');
let activeJobs = 0;
async function limited(operation) {
  if (activeJobs >= 2) throw identityError('AUTH_BUSY');
  activeJobs++;
  try { return await operation(); } finally { activeJobs--; }
}
function validatePassword(password) {
  if (typeof password !== 'string' || [...password].length < 12 || [...password].length > 128 || Buffer.byteLength(password) > 512) {
    throw identityError('INVALID_PASSWORD', 'Password must contain 12–128 characters');
  }
}
async function hashPassword(password) {
  validatePassword(password);
  return limited(() => argon2.hash(password, { type: argon2.argon2id, memoryCost: 19456, timeCost: 2, parallelism: 1 }));
}
async function verifyPassword(hash, password) {
  if (typeof password !== 'string' || Buffer.byteLength(password) > 512) return false;
  return limited(async () => { try { return await argon2.verify(hash, password); } catch { return false; } });
}
module.exports = { hashPassword, verifyPassword, validatePassword };
