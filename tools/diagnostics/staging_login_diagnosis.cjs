'use strict';
// Root-only diagnosis. Owner credentials, session secrets and MFA seeds are never
// selected/logged. Only the pre-existing synthetic observer is used for a probe.
const fs=require('node:fs'),cp=require('node:child_process'),https=require('node:https'),assert=require('node:assert/strict');
const base='/var/backups/thirdhand/access-C2g-camera-20261030T182905Z';
const origin='https://staging.uiea-thirdhand.com';
const report={at:new Date().toISOString(),sdkActions:0,ownerLoginAttempts:0};
const save=()=>fs.writeFileSync(base+'/login-diagnosis.json',JSON.stringify(report,null,2),{mode:0o600});
function request(path,{body,cookie,csrf}={}){
  return new Promise((resolve,reject)=>{
    const started=performance.now(),data=body===undefined?null:Buffer.from(JSON.stringify(body));
    const req=https.request({host:'127.0.0.1',port:443,servername:'staging.uiea-thirdhand.com',path,method:data?'POST':'GET',timeout:6000,headers:{Host:'staging.uiea-thirdhand.com',Origin:origin,...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...(data?{'Content-Type':'application/json','Content-Length':data.length}:{})}},res=>{
      const chunks=[];let bytes=0;res.on('data',chunk=>{bytes+=chunk.length;if(bytes>2000000)req.destroy();else chunks.push(chunk);});
      res.on('end',()=>{let json;try{json=JSON.parse(Buffer.concat(chunks));}catch{}resolve({status:res.statusCode,elapsedMs:Math.round(performance.now()-started),headers:res.headers,json});});
    });
    req.on('timeout',()=>req.destroy(Object.assign(Error('DIAG_TIMEOUT'),{code:'DIAG_TIMEOUT'})));req.on('error',reject);if(data)req.write(data);req.end();
  });
}
async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  report.api=cp.execFileSync('/usr/bin/systemctl',['show','thirdhand-stage.service','-p','MainPID','-p','NRestarts','-p','ActiveState','-p','MemoryCurrent'],{encoding:'utf8'}).trim();
  const events='/sys/fs/cgroup/system.slice/thirdhand-stage.service/memory.events';
  if(fs.existsSync(events))report.memoryEvents=fs.readFileSync(events,'utf8').trim();
  const ownerEmail=process.env.THIRDHAND_DIAG_OWNER_EMAIL;
  assert(typeof ownerEmail==="string"&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(ownerEmail),"Private THIRDHAND_DIAG_OWNER_EMAIL required");
  const ownerSql="'"+ownerEmail.replace(/'/g,"''")+"'";
  const sql=`BEGIN READ ONLY;
SET LOCAL statement_timeout='3s';
SELECT json_build_object('kind','ownerStatus','active',status='active','verified',email_verified_at IS NOT NULL,'mfaEnabled',EXISTS(SELECT 1 FROM auth.mfa_credentials m WHERE m.user_id=u.id AND m.kind='totp' AND m.enabled_at IS NOT NULL AND m.revoked_at IS NULL)) FROM auth.users u WHERE email=${ownerSql};
SELECT json_build_object('kind','ownerLoginWindows','attempts',r.attempts,'resetAtUtc',r.window_started_at+interval '15 minutes','remainingSeconds',GREATEST(0,ceil(extract(epoch FROM r.window_started_at+interval '15 minutes'-now())))) FROM security.rate_limits r WHERE bucket_hash IN (SELECT encode(sha256(convert_to('login:account:'||identifier,'UTF8')),'hex') FROM (SELECT lower(username) identifier FROM auth.users WHERE email=${ownerSql} UNION SELECT lower(email) FROM auth.users WHERE email=${ownerSql}) own);
SELECT json_build_object('kind','loginAudit','atUtc',created_at,'event',event_code,'code',context->>'code') FROM security.audit_events WHERE event_code IN ('identity.login.success','identity.login.denied') AND created_at>now()-interval '35 minutes' ORDER BY created_at DESC LIMIT 24;
SELECT json_build_object('kind','dbWaits','state',state,'waitType',wait_event_type,'count',count(*)) FROM pg_stat_activity WHERE datname='thirdhand_stage' GROUP BY state,wait_event_type;
COMMIT;`;
  report.database=cp.execFileSync('/usr/sbin/runuser',['-u','postgres','--','/usr/lib/postgresql/17/bin/psql','-X','-q','-At','-h','/run/thirdhand-stage-db','-p','55440','-d','thirdhand_stage','-v','ON_ERROR_STOP=1'],{input:sql,encoding:'utf8',timeout:8000}).trim().split('\n').filter(Boolean).map(line=>JSON.parse(line));
  const health=await request('/healthz');report.health={status:health.status,elapsedMs:health.elapsedMs};save();
  const fixture=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json')).accounts.find(a=>/^c2_/.test(a.username)&&/observer/.test(a.username));
  assert(fixture,'SYNTHETIC_OBSERVER_REQUIRED');let session;
  try{
    const login=await request('/api/v1/auth/login',{body:{login:fixture.username,password:fixture.password,requestedMode:'observe'}});
    report.syntheticLogin={status:login.status,elapsedMs:login.elapsedMs,errorCode:/^[A-Z_]+$/.test(login.json?.error||'')?login.json.error:null};save();
    if(login.status===200){
      session={cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken};
      const workspace=await request('/control',session);report.syntheticWorkspace={status:workspace.status,elapsedMs:workspace.elapsedMs};
    }
  }finally{
    if(session){const closed=await request('/api/v1/session/logout',{...session,body:{}});report.syntheticLogout={status:closed.status};}
    report.finishedAt=new Date().toISOString();save();
  }
  console.log(JSON.stringify(report));
}
main().catch(error=>{report.failure={type:error.name,code:/^[A-Z_]+$/.test(error.code||'')?error.code:null};save();console.log(JSON.stringify(report));process.exitCode=1;});
