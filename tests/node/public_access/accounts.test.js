'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { identityFixture } = require('./identity-fixture');
const { createAccounts } = require('../../../platform/identity/src/accounts');
const { createUsersRepository } = require('../../../platform/storage/src/users');
const {createMailer}=require('../../../platform/identity/src/mail');

test('registration cannot self-promote and verification is one-use without storing clear tokens or passwords', async t => {
  const f = await identityFixture(t);
  const result = await f.accounts.register({ username: 'Fresh_User', email: 'FRESH@example.invalid', displayName: 'Fresh', password: f.password, role: 'admin', locale: 'zh-CN' });
  const stored = await createUsersRepository(f.pool).findByLogin('fresh_user');
  assert.equal(stored.role, 'observer'); assert.equal(stored.status, 'pending_email');
  assert.match(stored.passwordHash, /^\$argon2id\$/); assert.notEqual(stored.passwordHash, f.password);
  assert.deepEqual(Object.keys(result).sort(), ['status','userId']);
  const clearToken = f.token(f.mailbox[0]);
  const dbToken = (await f.pool.query('SELECT token_hash FROM auth.one_time_tokens')).rows[0].token_hash;
  assert.notEqual(dbToken, clearToken); assert.equal(dbToken.length, 64);
  await assert.rejects(f.accounts.authenticate({ login: 'fresh_user', password: f.password }), { code: 'EMAIL_NOT_VERIFIED' });
  await f.accounts.verifyEmail({ token: clearToken });
  await assert.rejects(f.accounts.verifyEmail({ token: clearToken }), { code: 'INVALID_TOKEN' });
  assert.equal((await f.accounts.authenticate({ login: 'fresh_user', password: f.password })).mode, 'observe');
});

test('password is checked before administrator permission and unknown-account errors', async t => {
  const f = await identityFixture(t); await f.verified('observer');
  await assert.rejects(f.accounts.authenticate({ login: 'user_observer', password: 'wrong', requestedMode: 'admin' }), { code: 'INVALID_CREDENTIALS' });
  await assert.rejects(f.accounts.authenticate({ login: 'missing', password: 'wrong', requestedMode: 'admin' }), { code: 'INVALID_CREDENTIALS' });
  await assert.rejects(f.accounts.authenticate({ login: 'user_observer', password: f.password, requestedMode: 'admin' }), { code: 'ADMIN_PERMISSION_REQUIRED' });
  await assert.rejects(f.accounts.authenticate({ login: 'user_observer', password: f.password, requestedMode: 'root' }), { code: 'INVALID_INPUT' });
});

test('reset request is generic; reset token expires and successful reset revokes all sessions', async t => {
  const f = await identityFixture(t); const user = await f.verified('reset');
  const known = await f.accounts.requestPasswordReset({ email: 'reset@example.invalid' });
  const clearToken = f.token(f.mailbox.at(-1));
  const unknown = await f.accounts.requestPasswordReset({ email: 'absent@example.invalid' });
  assert.deepEqual(known, unknown);
  await f.pool.query(`INSERT INTO auth.sessions(user_id,token_hash,role_version,created_at,last_user_activity_at,idle_expires_at,absolute_expires_at)
    VALUES($1,$2,1,now(),now(),now()+interval '1 hour',now()+interval '1 day')`, [user.userId, 'e'.repeat(64)]);
  await f.accounts.resetPassword({ token: clearToken, password: 'New test only passphrase 576!' });
  await assert.rejects(f.accounts.resetPassword({ token: clearToken, password: f.password }), { code: 'INVALID_TOKEN' });
  await assert.rejects(f.accounts.authenticate({ login: 'user_reset', password: f.password }), { code: 'INVALID_CREDENTIALS' });
  assert.ok((await f.pool.query('SELECT revoked_at FROM auth.sessions')).rows[0].revoked_at);
  await f.accounts.requestPasswordReset({ email: 'reset@example.invalid' });
  const expired = f.token(f.mailbox.at(-1)); f.clock.value += 31 * 60000;
  await assert.rejects(f.accounts.resetPassword({ token: expired, password: f.password }), { code: 'INVALID_TOKEN' });
});

test('login limits are shared across application instances and do not leak account existence', async t => {
  const f = await identityFixture(t); await f.verified('limited');
  const second = createAccounts({ pool: f.pool, mfa: f.mfa, clock: f.clock, publicOrigin: 'https://thirdhand.example.invalid', mail: { async send() {} } });
  for (let i = 0; i < 8; i++) {
    await assert.rejects((i % 2 ? second : f.accounts).authenticate({ login: 'user_limited', password: 'wrong', sourceKey: 'test-source' }), { code: 'INVALID_CREDENTIALS' });
  }
  await assert.rejects(second.authenticate({ login: 'user_limited', password: f.password, sourceKey: 'test-source' }), { code: 'RATE_LIMITED' });
  f.clock.value += 16 * 60000;
  assert.equal((await second.authenticate({ login: 'user_limited', password: f.password, sourceKey: 'test-source' })).mode, 'observe');
});

test('missing mail configuration creates no unusable account and reset failures do not disclose account existence',async t=>{
  const f=await identityFixture(t);
  const disabled=createAccounts({pool:f.pool,mfa:f.mfa,mail:createMailer(),clock:f.clock,publicOrigin:'https://thirdhand.example.invalid'});
  await assert.rejects(disabled.register({username:'no_mail',email:'nomail@example.invalid',displayName:'No mail',password:f.password}),{code:'MAIL_UNAVAILABLE'});
  assert.equal((await f.pool.query('SELECT count(*)::int n FROM auth.users')).rows[0].n,0);
  await f.verified('mail_failure');
  const broken=createAccounts({pool:f.pool,mfa:f.mfa,mail:{async send(){throw Error('Sensitive SMTP diagnostic must never be public');}},clock:f.clock,publicOrigin:'https://thirdhand.example.invalid'});
  assert.deepEqual(await broken.requestPasswordReset({email:'mail_failure@example.invalid'}),await broken.requestPasswordReset({email:'unknown@example.invalid'}));
  const audit=(await f.pool.query("SELECT context FROM security.audit_events WHERE event_code='identity.mail.failed'")).rows;
  assert.equal(audit.length,1);assert.ok(!JSON.stringify(audit).includes('Sensitive SMTP'));
});
