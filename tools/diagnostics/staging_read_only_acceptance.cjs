'use strict';
// C3a: inspect persisted data and use an existing synthetic observer only.
// Never connects SDK, creates users, grants privileges, or prints credentials.
const fs=require('node:fs'),https=require('node:https'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {createHash}=require('node:crypto');
const root='/var/backups/thirdhand/access-C3a-sdk-readonly-20261031';
const deviceId='ee625a57-049a-4c5d-92e1-9578ab9d21c3';
const origin='https://staging.uiea-thirdhand.com';
function sql(query){return execFileSync('/usr/sbin/runuser',['-u','postgres','--','/usr/lib/postgresql/17/bin/psql','-X','-q','-At','-h','/run/thirdhand-stage-db','-p','55440','-d','thirdhand_stage','-c',query],{encoding:'utf8',maxBuffer:20*1024*1024}).trim();}
function rows(query){return sql(query).split('\n').filter(Boolean).map(line=>JSON.parse(line));}
function request(path,{body,cookie,csrf}={}){return new Promise((resolve,reject)=>{
  const data=body===undefined?null:Buffer.from(JSON.stringify(body));
  const req=https.request({host:'127.0.0.1',port:443,servername:'staging.uiea-thirdhand.com',path,method:data?'POST':'GET',headers:{Host:'staging.uiea-thirdhand.com',Origin:origin,...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...(data?{'Content-Type':'application/json','Content-Length':data.length}:{})},timeout:5000},res=>{
    const chunks=[];res.on('data',x=>chunks.push(x));res.on('end',()=>{let json;try{json=JSON.parse(Buffer.concat(chunks));}catch{}resolve({status:res.statusCode,headers:res.headers,json});});
  });req.on('error',()=>reject(Error('HTTP_TRANSPORT')));req.on('timeout',()=>req.destroy());if(data)req.write(data);req.end();
});}
async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  const report={startedAt:new Date().toISOString(),deviceId,source:'actual-hardware',sdkActionsByHarness:0,motionCommandsByHarness:0};
  const samples=rows(`SELECT row_to_json(s) FROM telemetry.robot_samples s WHERE device_id='${deviceId}' ORDER BY captured_at,sample_seq`);
  assert(samples.length>0);assert(samples.every(s=>s.extra.sourceMode==='hardware'&&s.sdk_connected===true&&s.moving===false));
  assert(samples.every(s=>s.joint_position_rad.length===6&&s.joint_position_rad.every((v,i)=>Math.abs(v-(s.extra.rawState.joints_deg??s.extra.rawState.joints)[i]*Math.PI/180)<1e-9)));
  const delays=samples.map(s=>Date.parse(s.received_at)-Date.parse(s.captured_at)).sort((a,b)=>a-b);
  report.samples={count:samples.length,first:samples[0].captured_at,last:samples.at(-1).captured_at,allHardware:true,allSixAxesMatchRawDegrees:true,movingSamples:0,latencyMs:{min:delays[0],median:delays[Math.floor(delays.length*.5)],p95:delays[Math.floor(delays.length*.95)],max:delays.at(-1)},clockQualities:[...new Set(samples.map(s=>s.clock_quality))],fieldAvailability:samples[0].field_availability};
  const batches=rows(`SELECT json_build_object('kind',b.stream_kind,'digest',b.digest,'payload',replace(encode(p.payload_bytes,'base64'),E'\\n',''),'rowCount',b.row_count) FROM telemetry.ingest_batches b JOIN telemetry.ingest_batch_payloads p ON p.batch_id=b.id WHERE b.device_id='${deviceId}' ORDER BY b.completed_at`);
  const batchCounts={};for(const b of batches){const data=Buffer.from(b.payload,'base64');assert.equal(createHash('sha256').update(data).digest('hex'),b.digest);assert.equal(JSON.parse(data).rows.length,b.rowCount);batchCounts[b.kind]=(batchCounts[b.kind]||0)+1;}
  report.exactRawBatches={count:batches.length,byStream:batchCounts,allDigestsVerified:true};
  report.commands=rows(`SELECT json_build_object('opcode',opcode,'state',state,'code',result->>'code','createdAt',created_at) FROM ops.commands WHERE device_id='${deviceId}' ORDER BY created_at`);
  assert(report.commands.some(c=>c.opcode==='connect'&&c.state==='completed'));
  assert(report.commands.some(c=>c.opcode==='disconnect'&&c.state==='stopped'));
  assert(report.commands.every(c=>['connect','disconnect'].includes(c.opcode)));
  report.leases=rows(`SELECT json_build_object('epoch',lease_epoch,'state',state,'reason',release_reason) FROM ops.control_leases WHERE device_id='${deviceId}' ORDER BY lease_epoch`);
  assert(report.leases.every(l=>l.state==='released'));
  report.sourceSequences=rows(`WITH source AS (SELECT extra->>'executorEpoch' AS epoch,(extra->>'sourceSequence')::bigint AS seq FROM telemetry.robot_samples WHERE device_id='${deviceId}' UNION ALL SELECT details->>'executorEpoch',(details->>'sourceSequence')::bigint FROM ops.device_events WHERE device_id='${deviceId}' AND details ? 'sourceSequence' UNION ALL SELECT e.details->>'executorEpoch',(e.details->>'sourceSequence')::bigint FROM ops.command_events e JOIN ops.commands c ON c.command_id=e.command_id WHERE c.device_id='${deviceId}' AND e.details ? 'sourceSequence') SELECT json_build_object('executorEpoch',epoch,'first',MIN(seq),'last',MAX(seq),'count',COUNT(*),'unique',COUNT(DISTINCT seq)) FROM source WHERE seq>0 GROUP BY epoch`);
  assert(report.sourceSequences.every(s=>s.first===1&&s.last===s.unique&&s.count===s.unique));
  report.invalidSamples=Number(sql(`SELECT COUNT(*) FROM telemetry.invalid_samples WHERE device_id='${deviceId}'`));assert.equal(report.invalidSamples,0);
  const fixture=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json'));
  const account=fixture.accounts.find(a=>a.username==='c2_observer');assert(account);
  const login=await request('/api/v1/auth/login',{body:{login:account.username,password:account.password,requestedMode:'observe'}});assert.equal(login.status,200);
  const session={cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken};
  try{
    const filter=new URLSearchParams({kind:'samples',deviceId,from:samples[0].captured_at,to:new Date().toISOString(),limit:'1'});
    const history=await request('/api/v1/history?'+filter,session);assert.equal(history.status,200);assert.equal(history.json.rows.length,1);
    const identities=await request('/api/v1/admin/users',session);assert.equal(identities.status,403);
    const lease=await request('/api/v1/control/lease',{...session,body:{deviceId}});assert.equal(lease.status,403);
    const command=await request('/api/v1/control/command',{...session,body:{deviceId}});assert.equal(command.status,403);
    report.observer={actualHardwareHistoryStatus:history.status,accountDirectoryDenied:identities.status,sdkLeaseDenied:lease.status,sdkCommandDenied:command.status};
  }finally{await request('/api/v1/session/logout',{...session,body:{}});}
  report.finishedAt=new Date().toISOString();report.boundedReadOnlyChecksPassed=true;
  report.fullMotionAccepted=false;report.realtimeTelemetryAccepted=false;
  fs.writeFileSync(root+'/read-only-acceptance.json',JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify(report));
}
main().catch(e=>{console.error(JSON.stringify({success:false,errorType:e.name,code:e.code||'ACCEPTANCE_ASSERTION'}));process.exitCode=1;});
