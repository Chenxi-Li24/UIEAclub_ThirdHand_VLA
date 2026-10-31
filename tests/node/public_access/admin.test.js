'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const { identityFixture } = require('./identity-fixture');
const { createSessions } = require('../../../platform/identity/src/sessions');
const { createCloudApi } = require('../../../services/cloud-api/src/server');
const { createUsersRepository } = require('../../../platform/storage/src/users');

test('HTTP rejects forged identities, cross-origin or CSRF writes, and all legacy control paths without connecting a proxy', async t => {
  const f = await identityFixture(t); const user = await f.verified('http');
  const sessions = createSessions({ pool: f.pool, csrfKey: randomBytes(32), clock: f.clock });
  const server = createCloudApi({ ...f, sessions, publicOrigin: 'https://thirdhand.example.invalid' });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = (path, body, headers = {}) => fetch(base + path, { method: 'POST', headers: { 'content-type': 'application/json', origin: 'https://thirdhand.example.invalid', ...headers }, body: JSON.stringify(body) });
  assert.equal((await post('/api/v1/auth/login',{login:'user_http',password:'wrong'})).status,401);
  const audit=(await f.pool.query("SELECT context FROM security.audit_events WHERE event_code='identity.login.denied'")).rows;
  assert.equal(audit.length,1);assert.ok(!JSON.stringify(audit).includes('wrong'));
  const login = await post('/api/v1/auth/login', { login: 'user_http', password: f.password, requestedMode: 'observe' });
  assert.equal(login.status, 200); const payload = await login.json();
  const cookie = login.headers.get('set-cookie').split(';')[0];
  assert.ok(payload.csrfToken); assert.ok(!JSON.stringify(payload).includes('passwordHash'));
  const protectedRead = await fetch(base + '/api/v1/admin/users', { headers: { cookie, 'x-user-role': 'admin', 'x-user-id': user.userId } });
  assert.equal(protectedRead.status, 403);
  assert.equal((await post('/api/v1/session/logout', {}, { cookie })).status, 403);
  assert.equal((await post('/api/v1/session/logout', {}, { cookie, 'x-csrf-token': payload.csrfToken, origin: 'https://attacker.invalid' })).status, 403);
  for (const path of ['/ws','/execution','/voice','/vision']) assert.equal((await fetch(base + path, { headers: { cookie } })).status, 404);
  assert.equal((await post('/api/v1/session/logout', {}, { cookie, 'x-csrf-token': payload.csrfToken })).status, 200);
  assert.equal((await fetch(base + '/api/v1/session', { headers: { cookie } })).status, 401);
});

test('administrators can disable accounts with immediate session revocation but cannot disable the final administrator',async t=>{
  const f=await identityFixture(t),a=await f.verified('status_admin'),b=await f.verified('status_observer');
  const users=createUsersRepository(f.pool);await users.bootstrapAdmin({verifiedUserId:a.userId});
  const sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock});
  const issued=await sessions.issue({userId:b.userId});
  await users.setStatus({actorId:a.userId,userId:b.userId,status:'disabled',expectedVersion:1,reason:'test deactivation'});
  assert.equal(await sessions.resolveSession({headers:{cookie:issued.cookie.split(';')[0]}}),null);
  await assert.rejects(f.accounts.authenticate({login:'user_status_observer',password:f.password}),{code:'INVALID_CREDENTIALS'});
  await assert.rejects(users.setStatus({actorId:a.userId,userId:a.userId,status:'disabled',expectedVersion:2,reason:'invalid final admin disable'}),{code:'23514'});
  const events=await f.pool.query("SELECT actor_user_id,object_id,context FROM security.audit_events WHERE event_code='identity.user.status_changed'");
  assert.equal(events.rows[0].actor_user_id,a.userId);assert.equal(events.rows[0].object_id,b.userId);
  assert.equal(events.rows[0].context.reason,'test deactivation');
  await assert.rejects(users.setStatus({actorId:a.userId,userId:b.userId,status:'active',expectedVersion:2,reason:{text:'object coercion'}}),{code:'INVALID_INPUT'});
});

test('administrator accounts in observer mode cannot list users; explicit admin MFA grants only business API access', async t => {
  const f = await identityFixture(t); const user = await f.verified('http_admin');
  await createUsersRepository(f.pool).bootstrapAdmin({ verifiedUserId: user.userId });
  const enrollment = await f.accounts.beginMfaSetup({ userId: user.userId, password: f.password });
  const OTPAuth = require('otpauth'), auth = OTPAuth.URI.parse(enrollment.uri);
  await f.mfa.confirmEnrollment({ userId: user.userId, totp: auth.generate({ timestamp: f.clock.value }) });
  f.clock.value += 30000;
  const sessions = createSessions({ pool: f.pool, csrfKey: randomBytes(32), clock: f.clock });
  const server = createCloudApi({ ...f, sessions, publicOrigin: 'https://thirdhand.example.invalid' });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const login = async mode => fetch(base + '/api/v1/auth/login', { method: 'POST', headers: { 'content-type':'application/json',origin:'https://thirdhand.example.invalid' }, body: JSON.stringify({ login:'user_http_admin', password:f.password,requestedMode:mode,totp:mode==='admin'?auth.generate({ timestamp:f.clock.value }):undefined }) });
  const observer = await login('observe'), observerCookie = observer.headers.get('set-cookie').split(';')[0];
  assert.equal((await fetch(base + '/api/v1/admin/users', { headers:{cookie:observerCookie} })).status, 403);
  const admin = await login('admin'), adminCookie = admin.headers.get('set-cookie').split(';')[0];
  const users = await fetch(base + '/api/v1/admin/users', { headers:{cookie:adminCookie} });
  assert.equal(users.status, 200);
  const response = await users.text(); assert.ok(response.includes('http_admin')); assert.ok(!response.includes('password_hash')); assert.ok(!response.includes('$argon2'));
  assert.equal((await fetch(base + '/api/v1/control/lease', { method:'POST',headers:{cookie:adminCookie,'content-type':'application/json',origin:'https://thirdhand.example.invalid','x-csrf-token':(await admin.json()).csrfToken},body:'{}' })).status, 503);
});
