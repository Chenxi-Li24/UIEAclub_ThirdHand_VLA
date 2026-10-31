'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { once } = require('node:events');
const { identityFixture } = require('./identity-fixture');
const { createSessions } = require('../../../platform/identity/src/sessions');
const { createUsersRepository } = require('../../../platform/storage/src/users');

test('sessions use hardened cookies and CSRF, do not refresh on telemetry reads, and expire with distinct mode limits', async t => {
  const f = await identityFixture(t); const user = await f.verified('session');
  const sessions = createSessions({ pool: f.pool, csrfKey: randomBytes(32), clock: f.clock });
  const issued = await sessions.issue({ userId: user.userId });
  assert.match(issued.cookie, /^__Host-thirdhand_session=/); assert.match(issued.cookie, /HttpOnly/);
  assert.match(issued.cookie, /Secure/); assert.match(issued.cookie, /SameSite=Lax/); assert.match(issued.cookie, /Path=\//);
  assert.ok(!issued.cookie.includes('Domain='));
  const request = { headers: { cookie: issued.cookie.split(';')[0] } };
  const principal = await sessions.resolveSession(request);
  assert.equal(principal.mode, 'observe'); assert.equal(principal.userId, user.userId);
  assert.equal(sessions.verifyCsrf({ headers: { 'x-csrf-token': issued.csrfToken } }, principal), true);
  assert.equal(sessions.verifyCsrf({ headers: { 'x-csrf-token': 'wrong' } }, principal), false);
  f.clock.value += 59 * 60000; assert.ok(await sessions.resolveSession(request));
  f.clock.value += 2 * 60000; assert.equal(await sessions.resolveSession(request), null);
  const admin = await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  const adminSession = await sessions.issue({ userId: admin.id, mode: 'admin', mfaVerifiedAt: f.clock.now() });
  const adminRequest = { headers: { cookie: adminSession.cookie.split(';')[0] } };
  f.clock.value += 14 * 60000; assert.ok(await sessions.resolveSession(adminRequest));
  f.clock.value += 2 * 60000; assert.equal(await sessions.resolveSession(adminRequest), null);
});

test('human activity extends idle timeout only up to the absolute deadline and logout keeps other sessions', async t => {
  const f = await identityFixture(t); const user = await f.verified('activity');
  const sessions = createSessions({ pool: f.pool, csrfKey: randomBytes(32), clock: f.clock });
  const first = await sessions.issue({ userId: user.userId }), second = await sessions.issue({ userId: user.userId });
  const req = issued => ({ headers: { cookie: issued.cookie.split(';')[0] } });
  const principal = await sessions.resolveSession(req(first));
  await sessions.revokeSession({ sessionId: principal.sessionId, reason: 'logout' });
  assert.equal(await sessions.resolveSession(req(first)), null); assert.ok(await sessions.resolveSession(req(second)));
  for (let hours = 1; hours < 24; hours++) {
    f.clock.value += 59 * 60000;
    const p = await sessions.resolveSession(req(second)); assert.ok(p);
    await sessions.recordHumanActivity(p);
  }
  f.clock.value += 61 * 60000;
  assert.equal(await sessions.resolveSession(req(second)), null);
});

test('role versions invalidate old sessions and PostgreSQL notifies other API instances after revocation', async t => {
  let sessions;
  t.after(() => sessions?.close());
  const f = await identityFixture(t); const user = await f.verified('notify');
  sessions = createSessions({ pool: f.pool, csrfKey: randomBytes(32), clock: f.clock });
  await sessions.start();
  const issued = await sessions.issue({ userId: user.userId });
  const req = { headers: { cookie: issued.cookie.split(';')[0] } };
  const principal = await sessions.resolveSession(req);
  const notification = once(sessions.events, 'revoked', { signal: AbortSignal.timeout(5000) });
  await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  assert.equal((await notification)[0].sessionId, principal.sessionId);
  assert.equal(await sessions.resolveSession(req), null);
});
