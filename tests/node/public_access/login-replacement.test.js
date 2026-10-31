'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomBytes}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {authRoute}=require('../../../services/cloud-api/src/routes/auth');

test('successful login replaces only this browser session; failed login keeps it',async t=>{
  const f=await identityFixture(t), oldUser=await f.verified('old_browser'), newUser=await f.verified('new_browser');
  const sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock});
  const old=await sessions.issue({userId:oldUser.userId}), other=await sessions.issue({userId:oldUser.userId});
  const request={headers:{cookie:old.cookie.split(';')[0]}};
  const response={writeHead(){},end(){}};
  const context={path:'/api/v1/auth/login',request,response,pool:f.pool,accounts:f.accounts,sessions,sourceKey:'a'.repeat(64)};
  await assert.rejects(authRoute({...context,body:{login:'user_new_browser',password:'invalid',requestedMode:'observe'}}),{code:'INVALID_CREDENTIALS'});
  assert.ok(await sessions.resolveSession(request));
  await authRoute({...context,body:{login:'user_new_browser',password:f.password,requestedMode:'observe'}});
  assert.equal(await sessions.resolveSession(request),null);
  assert.ok(await sessions.resolveSession({headers:{cookie:other.cookie.split(';')[0]}}));
  const row=(await f.pool.query('SELECT revocation_reason FROM auth.sessions WHERE id=$1',[old.sessionId])).rows[0];
  assert.equal(row.revocation_reason,'browser_login_replaced');
  assert.equal(newUser.userId.length,36);
});
