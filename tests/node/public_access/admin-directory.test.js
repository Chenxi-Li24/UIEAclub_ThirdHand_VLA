'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('administrator directory exposes registration metadata but never authentication secrets',async t=>{
  const f=await controlFixture(t);
  const server=createCloudApi({...f,publicOrigin:'https://thirdhand.example.invalid'});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base=`http://127.0.0.1:${server.address().port}`;
  const response=await fetch(base+'/api/v1/admin/users',{headers:{cookie:f.cookieFor(f.first)}});
  assert.equal(response.status,200);const page=await response.json();
  assert.ok(page.users.length>=2);
  for(const row of page.users){assert.ok(row.createdAt);assert.ok(row.emailVerifiedAt);assert.equal(typeof row.organization,'string');assert.equal(typeof row.displayName,'string');}
  assert.doesNotMatch(JSON.stringify(page),/password|hash|secret|recovery|token/i);
  const observer=await f.sessions.issue({userId:f.first.userId,mode:'observe'});
  assert.equal((await fetch(base+'/api/v1/admin/users',{headers:{cookie:observer.cookie.split(';')[0]}})).status,403);
});
