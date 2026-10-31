'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomBytes,randomUUID}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('observer media grants require cookie and CSRF; cached JWT alone cannot pass the private signaling gate after logout',async t=>{
  const f=await identityFixture(t),user=await f.verified('media_http'),sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock}),deviceId=randomUUID();let grants=0;
  const mediaService={async issueViewGrant(){grants++;return {token:'subscribe-only-fixture',viewerId:randomUUID()};},async authorizeSignaling(token,principal){if(token==='publisher-only-fixture'&&!principal)return {kind:'publisher'};if(token!=='subscribe-only-fixture'||!principal)throw Object.assign(Error(),{code:'FORBIDDEN'});return {kind:'viewer'};}};
  const server=createCloudApi({...f,sessions,mediaService,publicOrigin:'https://thirdhand.example.invalid',trustProxyLoopback:true});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base=`http://127.0.0.1:${server.address().port}`,session=await sessions.issue({userId:user.userId}),cookie=session.cookie.split(';')[0],headers={cookie,origin:'https://thirdhand.example.invalid','content-type':'application/json','x-csrf-token':session.csrfToken};
  const post=body=>fetch(base+'/api/v1/media/view',{method:'POST',headers,body:JSON.stringify(body)});
  assert.equal((await post({deviceId,publisher:true})).status,400);assert.equal(grants,0);
  assert.equal((await post({deviceId})).status,200);assert.equal(grants,1);
  const proxyHeaders={cookie,'x-original-uri':'/media/rtc?access_token=subscribe-only-fixture','x-original-origin':'https://thirdhand.example.invalid'};
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:proxyHeaders})).status,204);
  const v1Headers={...proxyHeaders,'x-original-uri':'/media/rtc/v1?access_token=subscribe-only-fixture&join_request=fixture'};
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:v1Headers})).status,204);
  const validationHeaders={cookie,'x-original-uri':'/media/rtc/v1/validate?access_token=subscribe-only-fixture','x-original-sec-fetch-site':'same-origin'};
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:validationHeaders})).status,204);
  for(const change of [{'x-original-sec-fetch-site':'cross-site'},{'x-original-origin':'https://other.invalid'},
    {'x-original-uri':'/media/rtc/v1?access_token=subscribe-only-fixture'},
    {'x-original-uri':'/media/rtc/v1/admin?access_token=subscribe-only-fixture'},
    {'x-original-uri':'/media/rtc/v1?access_token=subscribe-only-fixture&access_token=subscribe-only-fixture'}]){
    assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:{...validationHeaders,...change}})).status,403);
  }
  const nativeHeaders={'x-original-uri':'/media/rtc?sdk=python','x-original-authorization':'Bearer publisher-only-fixture'};
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:nativeHeaders})).status,204);
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:{...nativeHeaders,'x-original-uri':'/media/rtc/v1/validate?sdk=python'}})).status,204);
  for(const change of [{cookie},{'x-original-origin':'https://thirdhand.example.invalid'},
    {'x-original-authorization':'Bearer subscribe-only-fixture'},
    {'x-original-authorization':'Basic publisher-only-fixture'},
    {'x-original-authorization':'Bearer publisher-only-fixture, Bearer publisher-only-fixture'},
    {'x-original-uri':'/media/rtc?access_token=publisher-only-fixture'}]){
    assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:{...nativeHeaders,...change}})).status,403);
  }
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:{...proxyHeaders,'x-original-origin':'https://other.invalid'}})).status,403);
  await sessions.revokeSession({sessionId:session.sessionId,reason:'logout'});
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:proxyHeaders})).status,403);assert.equal((await post({deviceId})).status,401);
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:v1Headers})).status,403);
  assert.equal((await fetch(base+'/internal/v1/media-auth',{headers:validationHeaders})).status,403);
});
