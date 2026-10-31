'use strict';
const { identityError } = require('./errors');

function accountLink(publicOrigin, purpose, token) {
  const origin = new URL(publicOrigin);
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
    throw identityError('CONFIG_ERROR', 'Public account origin must be an HTTPS origin');
  }
  const paths = { verify_email: '/verify-email', reset_password: '/reset-password' };
  if (!paths[purpose]) throw identityError('INVALID_INPUT');
  const url = new URL(paths[purpose], origin);
  // Fragment is never sent to proxy access logs or Referer; the page submits it in a POST body.
  url.hash = new URLSearchParams({ token }).toString();
  return url.toString();
}

function createMailer({ transport } = {}) {
  function ensureAvailable(){if (!transport || typeof transport.send !== 'function') throw identityError('MAIL_UNAVAILABLE');}
  return {ensureAvailable, async send(message) {
    ensureAvailable();
    await transport.send(message);
  } };
}
module.exports = { accountLink, createMailer };
