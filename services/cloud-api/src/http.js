'use strict';
const { identityError } = require('../../../platform/identity/src/errors');
function json(response, status, data, headers = {}) {
  response.writeHead(status, { 'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store', ...headers });
  response.end(JSON.stringify(data));
}
async function readBody(request) {
  if (!/^application\/json(?:;|$)/i.test(request.headers['content-type'] || '')) throw identityError('UNSUPPORTED_MEDIA');
  let size = 0; const chunks = [];
  for await (const chunk of request) {
    size += chunk.length;
    if (size > 16384) throw identityError('BODY_TOO_LARGE');
    chunks.push(chunk);
  }
  try {
    const result = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error();
    return result;
  } catch { throw identityError('INVALID_INPUT'); }
}
function requireFields(body, allowed) {
  if (Object.keys(body).some(key => !allowed.includes(key))) throw identityError('INVALID_INPUT');
}
module.exports = { json, readBody, requireFields };
