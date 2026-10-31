'use strict';
const { EventEmitter } = require('node:events');
const { createSessionsRepository } = require('../../storage/src/sessions');
const { randomToken, digestToken, equalDigest } = require('./tokens');
const { createCsrf } = require('./csrf');

const COOKIE_NAME = '__Host-thirdhand_session';
function sessionCookie(token, seconds) { return `${COOKIE_NAME}=${token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=${seconds}`; }
function getToken(request) {
  const parts = String(request.headers?.cookie || '').split(';').map(part => part.trim()).filter(part => part.startsWith(`${COOKIE_NAME}=`));
  if (parts.length !== 1) return null;
  const token = parts[0].slice(COOKIE_NAME.length + 1);
  return /^[a-zA-Z0-9_-]{43}$/.test(token) ? token : null;
}

function createSessions({ pool, csrfKey, clock = { now: () => new Date() } }) {
  const repository = createSessionsRepository(pool), csrf = createCsrf(csrfKey), events = new EventEmitter();
  let listener = null;
  const api = {
    events,
    async start() {
      if (listener) return;
      listener = await pool.connect();
      listener.on('notification', message => {
        if (message.channel !== 'thirdhand_session_revoked') return;
        try {
          const value = JSON.parse(message.payload);
          if (/^[a-f0-9-]{36}$/i.test(value.sessionId)) events.emit('revoked', value);
        } catch { /* A malformed notification cannot create or restore authorization. */ }
      });
      listener.on('error', () => { events.emit('unavailable'); });
      await listener.query('LISTEN thirdhand_session_revoked');
    },
    async close() {
      if (!listener) return;
      const client = listener; listener = null;
      await client.query('UNLISTEN thirdhand_session_revoked').catch(() => {});
      client.removeAllListeners('notification'); client.release(true);
    },
    async issue({ userId, mode = 'observe', mfaVerifiedAt = null, clientLabel = '' }) {
      const token = randomToken(), csrfToken = csrf.forSession(token);
      const session = await repository.create({ userId, mode, mfaVerifiedAt, clientLabel, tokenHash: digestToken(token), csrfHash: digestToken(csrfToken), now: clock.now() });
      return { sessionId: session.id, csrfToken, mode: session.mode,
        cookie: sessionCookie(token, Math.floor((session.absoluteExpiresAt.getTime() - clock.now().getTime()) / 1000)) };
    },
    async resolveSession(request) {
      const token = getToken(request); if (!token) return null;
      const row = await repository.findByTokenHash(digestToken(token)); if (!row) return null;
      const now = clock.now().getTime(), csrfToken = csrf.forSession(token);
      if (row.revokedAt) return null;
      if (row.status !== 'active' || row.roleVersion !== row.currentRoleVersion ||
        now >= row.idleExpiresAt.getTime() || now >= row.absoluteExpiresAt.getTime() ||
        row.mode === 'admin' && (row.role !== 'admin' || !row.mfaVerifiedAt || row.mfaVerifiedAt.getTime() > now) ||
        !equalDigest(digestToken(csrfToken), row.csrfHash)) {
        await api.revokeSession({ sessionId: row.id, reason: 'session_invalid_or_expired' });
        return null;
      }
      return Object.freeze({ userId: row.userId, sessionId: row.id, role: row.role, mode: row.mode,
        roleVersion: row.roleVersion, mfaVerifiedAt: row.mfaVerifiedAt, csrfToken });
    },
    verifyCsrf(request, principal) { return csrf.verify(request.headers?.['x-csrf-token'], principal?.csrfToken); },
    async recordHumanActivity(principal) {
      const now = clock.now(), limit = new Date(now.getTime() + (principal.mode === 'admin' ? 15 : 60) * 60000);
      await pool.query(`UPDATE auth.sessions SET last_user_activity_at=$3,idle_expires_at=LEAST($4,absolute_expires_at)
        WHERE id=$1 AND user_id=$2 AND revoked_at IS NULL AND idle_expires_at>$3 AND absolute_expires_at>$3`, [principal.sessionId, principal.userId, now, limit]);
    },
    async revokeSession({ sessionId, reason }) {
      const changed = await repository.revoke({ sessionId, reason, now: clock.now() });
      if (changed) events.emit('revoked', { sessionId, reason });
      return changed;
    },
    clearCookie() { return sessionCookie('', 0); }
  };
  return api;
}
module.exports = { createSessions, COOKIE_NAME };
