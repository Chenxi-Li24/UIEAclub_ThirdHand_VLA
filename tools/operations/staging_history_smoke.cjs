'use strict';
// Operator-only C2 fixtures. Never connected to a device or composed by the API.
const fs=require('node:fs'),crypto=require('node:crypto'),cp=require('node:child_process'),https=require('node:https'),assert=require('node:assert/strict');
const base='/var/backups/thirdhand/access-C2-20261030T125221Z',release='/opt/thirdhand-stage/current',node='/opt/thirdhand-stage/node-v24.22.1/bin/node',host='staging.uiea-thirdhand.com';
function db(script){const code=`const {Pool}=require('${release}/node_modules/pg');const pool=new Pool({host:'/run/thirdhand-stage-db',port:55440,database:'thirdhand_stage',user:'postgres',max:1});(async()=>{try{${script}}finally{await pool.end()}})().catch(()=>{process.stderr.write('C2_FIXTURE_DB_FAILED');process.exitCode=1});`;return JSON.parse(cp.execFileSync('runuser',['-u','postgres','--',node,'-'],{input:code,cwd:release,encoding:'utf8'}));}
function request(endpoint,{body,cookie,csrf}={}){return new Promise((resolve,reject)=>{const bytes=body===undefined?null:Buffer.from(JSON.stringify(body));const req=https.request({hostname:'127.0.0.1',port:443,servername:host,path:endpoint,method:bytes?'POST':'GET',headers:{Host:host,...(bytes?{'Content-Type':'application/json','Content-Length':bytes.length,Origin:'https://'+host}:{}),...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{})},timeout:15000},res=>{const parts=[];res.on('data',x=>parts.push(x));res.on('end',()=>{const bytes=Buffer.concat(parts);let json;try{json=JSON.parse(bytes)}catch{}resolve({status:res.statusCode,headers:res.headers,bytes,json});});});req.on('timeout',()=>req.destroy(Error('TIMEOUT')));req.on('error',reject);req.end(bytes);});}
let step='preflight';
async function main(){
  assert.equal(process.getuid(),0);const stateFile=base+'/history-fixture.json';assert.equal(fs.existsSync(stateFile),false);
  const o=JSON.parse(fs.readFileSync(base+'/review-accounts.private.json')).accounts.find(a=>a.username==='c2_observer');
  const login=await request('/api/v1/auth/login',{body:{login:o.username,password:o.password,requestedMode:'observe'}});assert.equal(login.status,200);
  const session={cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken};
  const ids=Object.fromEntries(['device','boot','executor','run','command','batch'].map(k=>[k,crypto.randomUUID()]));
  const raw=Buffer.from(JSON.stringify({synthetic:true,source:'C2 acceptance fixture',samples:[{seq:0,position:[0,0,0,0,0,0]},{seq:1,position:[.1,0,0,0,0,0]},{seq:2,position:[.2,0,0,0,0,0]},{seq:3,invalid:'synthetic malformed sample'}]}));
  const state={...ids,from:new Date(Date.now()-3600000).toISOString(),to:new Date(Date.now()+3600000).toISOString(),rawDigest:crypto.createHash('sha256').update(raw).digest('hex')};fs.writeFileSync(stateFile,JSON.stringify(state,null,2),{mode:0o600});
  step='seed';
  db(`const x=${JSON.stringify(ids)},user=${JSON.stringify(o.userId)},raw=Buffer.from(${JSON.stringify(raw.toString('base64'))},'base64'),digest=${JSON.stringify(state.rawDigest)};
    await pool.query('BEGIN');
    await pool.query("INSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities,control_epoch) VALUES($1,'C2 Synthetic Robot — no hardware','C2-SYNTHETIC-ONLY',false,jsonb_build_object('synthetic',true,'remoteControl',false),7)",[x.device]);
    await pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version,ended_at) VALUES($1,$2,'synthetic-c2',now())",[x.boot,x.device]);
    await pool.query("INSERT INTO ops.execution_instances(executor_epoch,device_id,boot_id,worker_instance_id,ended_at) VALUES($1,$2,$3,'synthetic-c2',now())",[x.executor,x.device,x.boot]);
    await pool.query("INSERT INTO ops.runs(id,device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status,ended_at,versions) VALUES($1,$2,$3,$4,'user','C2 Synthetic Operator','dummy','completed',now(),jsonb_build_object('synthetic',true))",[x.run,x.device,x.boot,user]);
    await pool.query("INSERT INTO ops.commands(command_id,run_id,device_id,boot_id,executor_epoch,lease_epoch,sequence,opcode,schema_version,parameters,expires_at,state,result) VALUES($1,$2,$3,$4,$5,7,1,'synthetic_noop',1,jsonb_build_object('synthetic',true),now(),'completed',jsonb_build_object('synthetic',true))",[x.command,x.run,x.device,x.boot,x.executor]);
    await pool.query("INSERT INTO ops.command_events(command_id,edge_event_id,event_code,captured_at,details) VALUES($1,gen_random_uuid(),'synthetic.completed',now(),jsonb_build_object('synthetic',true))",[x.command]);
    await pool.query("INSERT INTO ops.device_events(device_id,boot_id,edge_event_id,event_code,level,captured_at,details) VALUES($1,$2,gen_random_uuid(),'synthetic.c2.fixture','info',now(),jsonb_build_object('synthetic',true))",[x.device,x.boot]);
    await pool.query("INSERT INTO telemetry.ingest_batches(id,device_id,boot_id,stream_kind,batch_seq,first_seq,last_seq,digest,row_count) VALUES($1,$2,$3,'robot_samples',0,0,3,$4,4)",[x.batch,x.device,x.boot,digest]);
    await pool.query('INSERT INTO telemetry.ingest_batch_payloads(batch_id,payload_bytes) VALUES($1,$2)',[x.batch,raw]);
    await pool.query("INSERT INTO telemetry.robot_samples(device_id,boot_id,sample_seq,captured_at,monotonic_ns,clock_quality,schema_version,run_id,command_id,joint_position_rad,sdk_connected,moving,extra) SELECT $1::uuid,$2::uuid,n,clock_timestamp()+n*interval '0.000001 second',n,'estimated',1,$3::uuid,$4::uuid,ARRAY[n*0.1,0,0,0,0,0]::float8[],false,false,jsonb_build_object('synthetic',true) FROM generate_series(0,2)n",[x.device,x.boot,x.run,x.command]);
    await pool.query("INSERT INTO telemetry.invalid_samples(device_id,boot_id,batch_id,sample_seq,reason_code,sanitized_fields) VALUES($1,$2,$3,3,'SYNTHETIC_MALFORMED',jsonb_build_object('synthetic',true))",[x.device,x.boot,x.batch]);
    await pool.query('COMMIT');console.log('{}');`);
  const counts={},exports=[];
  for(const kind of ['samples','runs','commands','command_events','device_events','invalid_samples','raw_batches']){
    step='history-'+kind;const filter={kind,deviceId:ids.device,from:state.from,to:state.to};let cursor=null,rows=[];
    do{const r=await request('/api/v1/history?'+new URLSearchParams({...filter,limit:'1',...(cursor?{cursor}:{})}),session);assert.equal(r.status,200);rows.push(...r.json.rows);cursor=r.json.nextCursor;}while(cursor);
    counts[kind]=rows.length;assert.equal(rows.length,kind==='samples'?3:1);
    if(kind==='raw_batches')assert.equal(crypto.createHash('sha256').update(Buffer.from(rows[0].payload_base64,'base64')).digest('hex'),state.rawDigest);
    const job=await request('/api/v1/exports',{...session,body:{filter,format:'ndjson'}});assert.equal(job.status,202);let status;
    for(let attempt=0;attempt<45;attempt++){status=await request('/api/v1/exports/'+job.json.id,session);assert.equal(status.status,200);if(['completed','failed'].includes(status.json.status))break;await new Promise(r=>setTimeout(r,1000));}
    assert.equal(status.json.status,'completed');const download=await request('/api/v1/exports/'+job.json.id+'/download',session);assert.equal(download.status,200);
    assert.equal(download.headers['x-export-sha256'],crypto.createHash('sha256').update(download.bytes).digest('hex'));assert.equal(download.bytes.toString().trim().split('\n').map(JSON.parse).filter(x=>x.type==='record').length,rows.length);
    assert.equal((await request('/api/v1/exports/'+job.json.id+'/download')).status,401);exports.push({kind,rows:rows.length,digest:download.headers['x-export-sha256']});
  }
  const result={success:true,checkedAt:new Date().toISOString(),syntheticOnly:true,hardwareCalls:0,observerFullHistoryCounts:counts,privateExports:exports,rawBytesPreserved:true};fs.writeFileSync(base+'/C2-history-export.json',JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result,null,2));
}
if(require.main===module)main().catch(e=>{console.error('C2_HISTORY_FAILED at '+step+' code '+(e.code||e.name));process.exitCode=1;});
module.exports={db,request};
