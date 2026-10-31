'use strict';
// Root-only C2g acceptance using existing synthetic accounts. No real user proof
// is read or created; no password, MFA seed, cookie, CSRF token or JWT is logged.
const fs=require('node:fs'),https=require('node:https'),assert=require('node:assert/strict');
const root='/var/backups/thirdhand/access-C2g-camera-20261030T182905Z';
const runtime='/opt/thirdhand-stage/current';
const OTPAuth=require(runtime+'/node_modules/otpauth');
const {TokenVerifier}=require(runtime+'/node_modules/livekit-server-sdk');
const origin='https://staging.uiea-thirdhand.com',deviceId='006e0cac-cf10-427e-a84c-42c260b3ac4e';

function request(path,{body,cookie,csrf,originHeader=origin,authorization}={}){
  return new Promise((resolve,reject)=>{
    const data=body===undefined?null:Buffer.from(JSON.stringify(body));
    const headers={Host:'staging.uiea-thirdhand.com',...(originHeader?{Origin:originHeader}:{}),
      ...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...(authorization?{Authorization:authorization}:{}),
      ...(data?{'Content-Type':'application/json','Content-Length':data.length}:{})};
    const req=https.request({host:'127.0.0.1',port:443,servername:'staging.uiea-thirdhand.com',path,method:data?'POST':'GET',headers,timeout:5000},res=>{
      const chunks=[];res.on('data',chunk=>chunks.push(chunk));res.on('end',()=>{
        const bytes=Buffer.concat(chunks);let json=null;try{json=JSON.parse(bytes);}catch{}
        resolve({status:res.statusCode,headers:res.headers,json});
      });
    });
    req.on('timeout',()=>req.destroy());req.on('error',e=>reject(Object.assign(Error('HTTP_TRANSPORT'),{code:e.code})));if(data)req.write(data);req.end();
  });
}

async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  const fixtures=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json'));
  const observer=fixtures.accounts.find(a=>/^c2_/.test(a.username)&&/observer/.test(a.username)),admin=fixtures.accounts.find(a=>/^c2_/.test(a.username)&&/admin/.test(a.username));
  assert(observer&&admin,'SYNTHETIC_FIXTURES_MISSING');
  const secrets=JSON.parse(fs.readFileSync(root+'/media-secrets.private.json')),verifier=new TokenVerifier(secrets.apiKey,secrets.apiSecret);
  const sessions=[],report={startedAt:new Date().toISOString(),deviceId,roles:[],sdkActions:0};
  try{
    for(const [account,mode] of [[observer,'observe'],[admin,'admin']]){
      const login=await request('/api/v1/auth/login',{body:{login:account.username,password:account.password,requestedMode:mode,...(mode==='admin'?{totp:OTPAuth.URI.parse(account.authenticatorUri).generate()}:{} )}});
      assert.equal(login.status,200,'SYNTHETIC_LOGIN');
      const session={cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken,mode};sessions.push(session);
      const actual=await request('/api/v1/session',session);assert.equal(actual.json.mode,mode);assert.equal(actual.json.role,mode==='admin'?'admin':'observer');
      const status=await request('/api/v1/media/status?deviceId='+deviceId,session);assert.equal(status.status,200);assert.equal(status.json.available,true);
      const granted=await request('/api/v1/media/view',{...session,body:{deviceId}});assert.equal(granted.status,200);
      session.grant=granted.json;
      const claims=await verifier.verify(session.grant.token,0);assert.equal(claims.video.canPublish,false);assert.equal(claims.video.canPublishData,false);assert.equal(claims.video.canSubscribe,true);
      const signal='/media/rtc/validate?access_token='+encodeURIComponent(session.grant.token);
      const validation=await request(signal,session);assert.equal(validation.status,200,'VIEWER_SIGNAL_VALIDATION');
      assert.equal((await request(signal,{originHeader:origin})).status,403,'COOKIE_REQUIRED');
      assert.equal((await request(signal,{...session,originHeader:'https://other.invalid'})).status,403,'ORIGIN_REQUIRED');
      assert.equal((await request('/media/rtc/validate',{authorization:'Bearer '+session.grant.token,originHeader:null})).status,403,'VIEWER_BEARER_FORBIDDEN');
      const sdk=await request('/api/v1/sdk/connect',{...session,body:{deviceId}});assert.equal(sdk.status,mode==='admin'?503:403);
      report.roles.push({role:actual.json.role,mode,viewGrant:granted.status,signalValidation:validation.status,sourceFresh:status.json.sourceFresh,sdkDeniedStatus:sdk.status,subscribeOnly:true});
    }
    assert.equal((await request('/api/v1/media/view',{...sessions[0],body:{deviceId}})).status,429,'TWO_VIEWER_LIMIT');report.thirdViewRejected=true;
    const revoked=sessions[0],oldSignal='/media/rtc/validate?access_token='+encodeURIComponent(revoked.grant.token);
    assert.equal((await request('/api/v1/session/logout',{...revoked,body:{}})).status,200);
    assert.equal((await request(oldSignal,revoked)).status,403,'LOGOUT_REJOIN_DENIED');report.logoutRejoinDenied=true;revoked.loggedOut=true;
    report.success=true;
  }finally{
    for(const session of sessions){
      if(session.loggedOut)continue;
      if(session.grant)await request('/api/v1/media/close',{...session,body:{viewerId:session.grant.viewerId}}).catch(()=>{});
      await request('/api/v1/session/logout',{...session,body:{}}).catch(()=>{});
    }
  }
  report.finishedAt=new Date().toISOString();fs.writeFileSync(root+'/camera-auth-acceptance.json',JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify(report));
}
main().catch(e=>{console.error(JSON.stringify({success:false,code:e.code||e.message}));process.exitCode=1;});
