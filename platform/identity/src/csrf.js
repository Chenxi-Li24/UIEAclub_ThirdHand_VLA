'use strict';
const { createHmac, timingSafeEqual } = require('node:crypto');
function createCsrf(key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) throw new Error('Separate 32-byte CSRF key required');
  return {
    forSession(token) { return createHmac('sha256', key).update(`thirdhand:csrf:${token}`).digest('base64url'); },
    verify(provided, expected) {
      if (typeof provided !== 'string' || typeof expected !== 'string' || provided.length !== 43 || expected.length !== 43) return false;
      return timingSafeEqual(Buffer.from(provided), Buffer.from(expected));
    }
  };
}
module.exports = { createCsrf };
