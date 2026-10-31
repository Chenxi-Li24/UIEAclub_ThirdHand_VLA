'use strict';
// Existing synthetic accounts only; downloads stay in memory. No SDK requests.
const fs=require('node:fs'),https=require('node:https'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto'),{execFileSync}=require('node:child_process');
const runtime='/opt/thirdhand-stage/current',root='/var/backups/thirdhand/access-C5-history-display-20261031';
const OTPAuth=require(runtime+'/node_modules/otpauth');
const deviceId='ee625a57-049a-4c5d-92e1-9578ab9d21c3';
function count(query){return Number(execFileSync('/usr/sbin/runuser',['-u','postgres','--','/usr/lib/postgresql/17/bin/psql','-X','-q','-At','-h','/run/thirdhand-stage-db','-p','55440','-d','thirdhand_stage','-c',query],{encoding:'utf8'}).trim());}
function request(path,{body,cookie,csrf}={}){return new Promise((resolve,reject)=>{
  const data=body===undefined?null:Buffer.from(JSON.stringify(body));
  const req=https.request({host:'127.0.0.1',port:443,servername:'staging.uiea-thirdhand.com',path,method:data?'POST':'GET',headers:{Host:'staging.uiea-thirdhand.com',Origin:'https://staging.uiea-thirdhand.com',...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...(data?{'Content-Type':'application/json','Content-Length':data.length}:{})},timeout:8000},res=>{
    const chunks=[];res.on('data',x=>chunks.push(x));res.on('end',()=>{const bytes=Buffer.concat(chunks);let json;try{json=JSON.parse(bytes);}catch{}resolve({status:res.statusCode,headers:res.headers,json,bytes});});
  });req.on('timeout',()=>req.destroy());req.on('error',()=>reject(Error('HTTP_TRANSPORT')));if(data)req.write(data);req.end();
});}
function csv(bytes){
  assert.equal(bytes.subarray(0,3).toString('hex'),'efbbbf');
  const text=bytes.toString('utf8').slice(1),rows=[];let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];if(ch==='"'){if(quoted&&text[i+1]==='"'){cell+='"';i++;}else quoted=!quoted;}
    else if(!quoted&&ch===','){row.push(cell);cell='';}
    else if(!quoted&&(ch==='\r'||ch==='\n')){if(ch==='\r'&&text[i+1]==='\n')i++;row.push(cell);rows.push(row);row=[];cell='';}
    else cell+=ch;
  }
  assert.equal(quoted,false);if(cell||row.length){row.push(cell);rows.push(row);}return rows;
}
async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  const fixtures=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json'));
  const sessions=[],report={startedAt:new Date().toISOString(),sdkActions:0,motionCommands:0};
  try{
    for(const [name,mode]of [['c2_admin','admin'],['c2_observer','observe']]){
      const account=fixtures.accounts.find(x=>x.username===name);assert(account);
      const login=await request('/api/v1/auth/login',{body:{login:account.username,password:account.password,requestedMode:mode,...(mode==='admin'?{totp:OTPAuth.URI.parse(account.authenticatorUri).generate()}:{})}});
      assert.equal(login.status,200,'SYNTHETIC_LOGIN');sessions.push({cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken});
    }
    const [admin,observer]=sessions;
    const historyPage=await request('/history',observer);assert.equal(historyPage.status,200);
    for(const id of ['history-from-date','history-from-time','history-to-date','history-to-time'])assert(historyPage.bytes.toString().includes('id="'+id+'"'));
    const dateModule=await request('/control-assets/js/history-dates.js',observer);assert.equal(dateModule.status,200);
    assert.equal((await request('/control-assets/js/history-dates.js')).status,401);
    const directory=await request('/api/v1/admin/users',admin);assert.equal(directory.status,200);
    const current=new Date(),query=new URLSearchParams({kind:'samples',from:new Date(current.getTime()-86400000).toISOString(),to:current.toISOString()});
    const initial=await request('/api/v1/history?'+query,observer);assert.equal(initial.status,200);assert(initial.json.rows.length>0);assert(initial.json.nextCursor);
    report.display={separateDateTimeInputs:4,protectedDateModule:true,memberRows:directory.json.users.length,last24HoursFirstPageRows:initial.json.rows.length,moreHistoricalRecords:true};
    const members=await request('/api/v1/admin/users/export',admin);assert.equal(members.status,200);
    assert.match(members.headers['content-disposition'],/^attachment; filename="thirdhand-members-.*\.csv"$/);assert.equal(members.headers['cache-control'],'no-store');
    const memberRows=csv(members.bytes);assert.deepEqual(memberRows[0],['id','username','display_name','email','organization','role','status','locale','registered_at_utc','email_verified_at_utc']);
    const memberCount=count('SELECT COUNT(*) FROM auth.users');assert.equal(memberRows.length-1,memberCount);assert(memberRows.every(r=>r.length===10));
    const forbidden=await request('/api/v1/admin/users/export',observer);assert.equal(forbidden.status,403);
    report.members={status:200,rowCount:memberCount,columnCount:10,utf8Bom:true,credentialFieldsExcluded:true,observerDeniedStatus:forbidden.status};
    const filter={kind:'samples',deviceId,from:'2026-10-31T09:47:00Z',to:'2026-10-31T09:48:00Z'};
    const expected=count(`SELECT COUNT(*) FROM telemetry.robot_samples WHERE device_id='${deviceId}' AND captured_at>='${filter.from}' AND captured_at<'${filter.to}'`);
    const created=await request('/api/v1/exports',{...observer,body:{filter,format:'csv'}});assert.equal(created.status,202);
    const id=created.json.id;let job;
    for(let attempt=0;attempt<40;attempt++){
      const result=await request('/api/v1/exports/'+id,observer);assert.equal(result.status,200);job=result.json;
      if(job.status==='completed'||job.status==='failed')break;
      await new Promise(resolve=>setTimeout(resolve,250));
    }
    assert.equal(job.status,'completed',job.errorCode||'EXPORT_NOT_COMPLETED');assert.equal(Number(job.rowCount),expected);
    const file=await request('/api/v1/exports/'+id+'/download',observer);assert.equal(file.status,200);
    const rows=csv(file.bytes),columns=rows[0];assert.equal(rows.length-1,expected);
    const hash=createHash('sha256').update(file.bytes).digest('hex');assert.equal(hash,job.digest);assert.equal(hash,file.headers['x-export-sha256']);
    assert(rows.every(row=>row.length===columns.length));
    const position=Array.from({length:6},(_,i)=>columns.indexOf(`j${i+1}_position_deg`));assert(position.every(i=>i>=0));
    const missing=columns.indexOf('j1_current_a');assert(missing>=0);
    for(const row of rows.slice(1)){assert.equal(row[columns.indexOf('source_mode')],'hardware');assert.equal(row[columns.indexOf('moving')],'false');assert(position.every(i=>Number.isFinite(Number(row[i]))&&row[i]!==''));assert.equal(row[missing],'');}
    const anonymous=await request('/api/v1/exports/'+id+'/download');assert([401,403].includes(anonymous.status));
    const other=await request('/api/v1/exports/'+id+'/download',admin);assert.equal(other.status,404);
    report.robotData={status:200,rowCount:expected,columnCount:columns.length,sixMeasuredAngles:true,missingSensorsBlank:true,utf8Bom:true,digestVerified:true,anonymousDeniedStatus:anonymous.status,otherSessionOwnerDeniedStatus:other.status};
    report.success=true;
  }finally{for(const session of sessions)await request('/api/v1/session/logout',{...session,body:{}}).catch(()=>{});}
  report.finishedAt=new Date().toISOString();fs.writeFileSync(root+'/table-download-acceptance.json',JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify(report));
}
main().catch(e=>{console.error(JSON.stringify({success:false,errorType:e.name,code:e.code||e.message}));process.exitCode=1;});
