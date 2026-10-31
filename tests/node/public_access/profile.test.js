'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomBytes}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('the account provider edits only the authenticated profile and does not silently change verified email',async t=>{
  const f=await identityFixture(t),user=await f.verified('profile');
  const sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock}),issued=await sessions.issue({userId:user.userId});
  const server=createCloudApi({...f,sessions,publicOrigin:'https://thirdhand.example.invalid'});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const url=`http://127.0.0.1:${server.address().port}/api/v1/me/profile`,headers={cookie:issued.cookie.split(';')[0]};
  assert.equal((await fetch(url,{headers})).status,200);
  const save=body=>fetch(url,{method:'POST',headers:{...headers,origin:'https://thirdhand.example.invalid','content-type':'application/json','x-csrf-token':issued.csrfToken},body:JSON.stringify(body)});
  const result=await save({displayName:'Updated Name',email:'profile@example.invalid',organization:'Lab'});assert.equal(result.status,200);assert.equal((await result.json()).displayName,'Updated Name');
  assert.equal((await save({displayName:'Other',email:'other@example.invalid',organization:'Lab'})).status,400);
  assert.equal((await save({displayName:'Other',userId:'forged'})).status,400);
  assert.equal((await f.pool.query('SELECT email FROM auth.users WHERE id=$1',[user.userId])).rows[0].email,'profile@example.invalid');
});
