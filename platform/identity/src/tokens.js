'use strict';
const { randomBytes, createHash, timingSafeEqual } = require('node:crypto');
const randomToken = () => randomBytes(32).toString('base64url');
const digestToken = token => createHash('sha256').update(String(token)).digest('hex');
function equalDigest(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !/^[a-f0-9]{64}$/.test(a) || !/^[a-f0-9]{64}$/.test(b)) return false;
  return timingSafeEqual(Buffer.from(a, 'hex'), Buffer.from(b, 'hex'));
}
module.exports = { randomToken, digestToken, equalDigest };
