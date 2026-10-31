'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { identityFixture } = require('./identity-fixture');
const { createUsersRepository } = require('../../../platform/storage/src/users');
const { createMfa } = require('../../../platform/identity/src/mfa');

test('MFA preparation verifies the password and preserves an already enabled authenticator',async t=>{
  const f=await identityFixture(t),user=await f.verified('prepare');
  await createUsersRepository(f.pool).bootstrapAdmin({verifiedUserId:user.userId});
  await assert.rejects(f.accounts.prepareMfa({userId:user.userId,password:'wrong'}),{code:'INVALID_CREDENTIALS'});
  assert.equal((await f.pool.query('SELECT count(*)::int AS n FROM auth.mfa_credentials')).rows[0].n,0);
  const prepared=await f.accounts.prepareMfa({userId:user.userId,password:f.password});assert.equal(prepared.enrolled,false);
  const authenticator=require('otpauth').URI.parse(prepared.uri);await f.mfa.confirmEnrollment({userId:user.userId,totp:authenticator.generate({timestamp:f.clock.value})});
  const before=(await f.pool.query("SELECT id,encrypted_secret FROM auth.mfa_credentials WHERE kind='totp'")).rows;
  assert.deepEqual(await f.accounts.prepareMfa({userId:user.userId,password:f.password}),{enrolled:true});
  assert.deepEqual((await f.pool.query("SELECT id,encrypted_secret FROM auth.mfa_credentials WHERE kind='totp'")).rows,before);
  await assert.rejects(f.accounts.authenticate({login:'user_prepare',password:f.password,requestedMode:'admin'}),{code:'MFA_REQUIRED'});
});

test('admin login requires MFA; an account may still use observer mode without taking control', async t => {
  const f = await identityFixture(t); const user = await f.verified('admin');
  await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  await assert.rejects(f.accounts.authenticate({ login: 'user_admin', password: f.password, requestedMode: 'admin' }), { code: 'MFA_ENROLLMENT_REQUIRED' });
  const proof = await f.accounts.authenticate({ login: 'user_admin', password: f.password });
  assert.equal(proof.mode, 'observe'); assert.equal(proof.role, 'admin');
  await assert.rejects(f.accounts.beginMfaSetup({ userId: user.userId, password: 'wrong' }), { code: 'INVALID_CREDENTIALS' });
});

test('TOTP setup is encrypted and activated only after proof; replay and reused recovery codes fail', async t => {
  const f = await identityFixture(t); const user = await f.verified('totp');
  await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  const enrollment = await f.accounts.beginMfaSetup({ userId: user.userId, password: f.password });
  const OTPAuth = require('otpauth'); const authenticator = OTPAuth.URI.parse(enrollment.uri);
  const credential = (await f.pool.query('SELECT encrypted_secret,enabled_at FROM auth.mfa_credentials WHERE user_id=$1', [user.userId])).rows[0];
  assert.ok(credential.encrypted_secret); assert.equal(credential.enabled_at, null);
  assert.ok(!credential.encrypted_secret.includes(authenticator.secret.base32));
  await assert.rejects(f.accounts.authenticate({ login: 'user_totp', password: f.password, requestedMode: 'admin', totp: authenticator.generate({ timestamp: f.clock.value }) }), { code: 'MFA_ENROLLMENT_REQUIRED' });
  const setup = await f.mfa.confirmEnrollment({ userId: user.userId, totp: authenticator.generate({ timestamp: f.clock.value }) });
  assert.equal(setup.recoveryCodes.length, 10);
  await assert.rejects(f.accounts.authenticate({ login: 'user_totp', password: f.password, requestedMode: 'admin', totp: authenticator.generate({ timestamp: f.clock.value }) }), { code: 'MFA_INVALID' });
  f.clock.value += 30000;
  const admin = await f.accounts.authenticate({ login: 'user_totp', password: f.password, requestedMode: 'admin', totp: authenticator.generate({ timestamp: f.clock.value }) });
  assert.equal(admin.mode, 'admin'); assert.ok(admin.mfaVerifiedAt);
  const recovery = setup.recoveryCodes[0];
  assert.equal((await f.accounts.authenticate({ login: 'user_totp', password: f.password, requestedMode: 'admin', recoveryCode: recovery })).mode, 'admin');
  await assert.rejects(f.accounts.authenticate({ login: 'user_totp', password: f.password, requestedMode: 'admin', recoveryCode: recovery }), { code: 'MFA_INVALID' });
  const badKeys = createMfa({ pool: f.pool, keyId: 'different', keys: new Map([['different', Buffer.alloc(32, 3)]]), clock: f.clock });
  await assert.rejects(badKeys.verify({ userId: user.userId, totp: authenticator.generate({ timestamp: f.clock.value + 30000 }) }), /key.*unavailable/i);
});

test('password reset preserves MFA and cannot turn an admin account into a password-only admin session', async t => {
  const f = await identityFixture(t); const user = await f.verified('reset_mfa');
  await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  const enrollment = await f.accounts.beginMfaSetup({ userId: user.userId, password: f.password });
  const OTPAuth = require('otpauth'); const authenticator = OTPAuth.URI.parse(enrollment.uri);
  await f.mfa.confirmEnrollment({ userId: user.userId, totp: authenticator.generate({ timestamp: f.clock.value }) });
  await f.accounts.requestPasswordReset({ email: 'reset_mfa@example.invalid' });
  await f.accounts.resetPassword({ token: f.token(f.mailbox.at(-1)), password: 'Reset MFA test passphrase 597!' });
  await assert.rejects(f.accounts.authenticate({ login: 'user_reset_mfa', password: 'Reset MFA test passphrase 597!', requestedMode: 'admin' }), { code: 'MFA_REQUIRED' });
  assert.equal((await f.pool.query("SELECT count(*)::int n FROM auth.mfa_credentials WHERE kind='totp' AND enabled_at IS NOT NULL AND revoked_at IS NULL")).rows[0].n, 1);
});

test('MFA enrollment confirmation has a shared attempt limit',async t=>{
  const f=await identityFixture(t),user=await f.verified('mfa_limit');
  await createUsersRepository(f.pool).bootstrapAdmin({verifiedUserId:user.userId});
  await f.accounts.beginMfaSetup({userId:user.userId,password:f.password});
  for(let i=0;i<8;i++)await assert.rejects(f.mfa.confirmEnrollment({userId:user.userId,totp:'invalid'}),{code:'MFA_INVALID'});
  await assert.rejects(f.mfa.confirmEnrollment({userId:user.userId,totp:'invalid'}),{code:'RATE_LIMITED'});
});
