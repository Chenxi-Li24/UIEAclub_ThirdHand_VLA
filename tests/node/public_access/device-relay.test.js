'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {execFile}=require('node:child_process');
const {promisify}=require('node:util');
const {once}=require('node:events');
const {randomUUID,X509Certificate,sign,generateKeyPairSync}=require('node:crypto');
const https=require('node:https');
const {WebSocket}=require('ws');
const {createDeviceRelay}=require('../../../services/device-relay/src/server');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');
const run=promisify(execFile), python=process.env.EDGE_TEST_PYTHON||'python';
function nextMessage(ws){return new Promise((resolve,reject)=>{
  const cleanup=()=>{ws.off('message',message);ws.off('close',closed);ws.off('error',failed);};
  const message=value=>{cleanup();resolve(value);},closed=()=>{cleanup();reject(Error('Socket closed'));},failed=error=>{cleanup();reject(error);};
  ws.once('message',message);ws.once('close',closed);ws.once('error',failed);
});}

async function fixture(t,{control=false,ingestBatch,mediaPublisher}={}){
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-relay-'));
  const children=[];
  t.after(async()=>{for(const child of children)if(child.exitCode===null&&child.signalCode===null){const exited=once(child,'close');child.kill();await exited;}const checked=path.resolve(dir);assert.equal(path.dirname(checked),path.resolve(os.tmpdir()));assert.ok(path.basename(checked).startsWith('thirdhand-relay-'));await fs.rm(checked,{recursive:true,force:true,maxRetries:5,retryDelay:50});});
  await run(python,['tests/python/edge_agent/pki_fixture.py',dir]);
  const pem=async label=>fs.readFile(path.join(dir,label)), cert=new X509Certificate(await pem('device.pem'));
  const identity={id:randomUUID(),certificateId:randomUUID(),fingerprint:cert.fingerprint256.replaceAll(':','').toLowerCase(),publicKey:cert.publicKey,remoteControlEnabled:control};
  let enabled=true;
  let binding=identity;
  const store={async resolveCertificate(fingerprint){return enabled&&fingerprint===identity.fingerprint?binding:null;},async registerExecution(){return true;}};
  const relay=createDeviceRelay({store,ingestBatch,mediaPublisher,tls:{key:await pem('server.key'),cert:await pem('server.pem'),ca:await pem('ca.pem')},handshakeTimeoutMs:1000});
  await new Promise(resolve=>relay.server.listen(0,'127.0.0.1',resolve));
  t.after(()=>relay.close());
  const url=`wss://localhost:${relay.server.address().port}/edge/v1/connect`;
  async function socket(label='device',options={}){
    const ws=new WebSocket(url,{key:await pem(`${label}.key`),cert:await pem(`${label}.pem`),ca:await pem('ca.pem'),...options});
    await once(ws,'open');return ws;
  }
  async function auth(ws,{deviceId=identity.id,bootId=randomUUID(),executorEpoch=null,signer='device'}={}){
    const challenge=nextMessage(ws);ws.send(JSON.stringify({type:'hello',protocol:1,deviceId,bootId,executorEpoch,agentVersion:'0.1.0',capabilities:[executorEpoch?'control':'probe']}));
    const envelope=JSON.parse(await challenge);
    const welcome=nextMessage(ws);
    ws.send(JSON.stringify({type:'proof',signatureBase64url:sign(null,Buffer.from(envelope.payloadBase64url,'base64url'),await pem(`${signer}.key`)).toString('base64url')}));
    return JSON.parse(await welcome);
  }
  return {dir,relay,identity,url,socket,auth,pem,track(child){children.push(child);return child;},disable(){enabled=false;},rebind(){binding={...identity,id:randomUUID()};}};
}

test('mTLS identity requires device key proof; reconnected device gets a fresh unauthorised context',async t=>{
  const f=await fixture(t), first=await f.socket(), welcome=await f.auth(first);
  assert.equal(welcome.type,'welcome');assert.equal(welcome.controlAuthorized,false);assert.equal(welcome.context.executorEpoch,null);
  const pong=once(first,'message');first.send(JSON.stringify({type:'ping',nonce:'test-heartbeat'}));assert.equal(JSON.parse((await pong)[0]).nonce,'test-heartbeat');
  const closed=once(first,'close'), second=await f.socket(), newer=await f.auth(second);
  assert.notEqual(newer.context.connectionId,welcome.context.connectionId);await closed;
  assert.equal(f.relay.devices.get(f.identity.id).connectionId,newer.context.connectionId);
  f.disable();const revoked=once(second,'close');second.send(JSON.stringify({type:'ping',nonce:'after-revoke'}));await revoked;
  assert.equal(f.relay.devices.get(f.identity.id),null);
});

test('bound executor is unavailable for commands until local binding ACK; replies are connection scoped',async t=>{
  const f=await fixture(t,{control:true}),ws=await f.socket(),welcome=await f.auth(ws,{executorEpoch:randomUUID()});
  assert.equal(f.relay.devices.get(f.identity.id).controlAccepted,false);
  const ack=nextMessage(ws);ws.send(JSON.stringify({type:'bound',executorEpoch:welcome.context.executorEpoch,hardwareFingerprint:'c'.repeat(64)}));
  assert.equal(JSON.parse(await ack).type,'bound_ack');assert.equal(f.relay.devices.get(f.identity.id).controlAccepted,true);
  const keys=generateKeyPairSync('ed25519'),signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey});
  const now=Date.now(),envelope=signer.sign({schema:1,purpose:'lease_grant',...welcome.context,leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:now,expiresAt:now+1000});
  const outgoing=nextMessage(ws),result=f.relay.devices.request(f.identity.id,envelope);
  const message=JSON.parse(await outgoing);assert.equal(message.type,'request');
  ws.send(JSON.stringify({type:'result',requestId:message.requestId,outcome:{state:'active',leaseId:'test-only',leaseEpoch:1}}));
  assert.equal((await result).state,'active');
  const pendingMessage=nextMessage(ws),lost=assert.rejects(f.relay.devices.request(f.identity.id,envelope));await pendingMessage;
  const newer=await f.socket();await f.auth(newer,{executorEpoch:randomUUID()});await lost;
  assert.equal(f.relay.devices.get(f.identity.id).controlAccepted,false);
});

test('a probe cannot replace an existing bound-executor connection',async t=>{
  const f=await fixture(t,{control:true}),control=await f.socket(),welcome=await f.auth(control,{executorEpoch:randomUUID()});
  const probe=await f.socket();await assert.rejects(f.auth(probe));
  assert.equal(f.relay.devices.get(f.identity.id).connectionId,welcome.context.connectionId);assert.equal(control.readyState,WebSocket.OPEN);
});

test('media publisher lease uses separate mTLS plus device-signed current context; it never authorizes SDK control',async t=>{
  const accepted=[],keys=generateKeyPairSync('ed25519'),signer=createEnvelopeSigner({keyId:'media-test',privateKey:keys.privateKey});
  const f=await fixture(t,{mediaPublisher:async(context,report)=>{accepted.push(report);return signer.sign({schema:1,...context,purpose:'media_publish',issuedAt:Date.now(),expiresAt:Date.now()+950});}});
  const ws=await f.socket(),welcome=await f.auth(ws),context=welcome.context;
  const report={schema:1,purpose:'media_report',context,publisherId:randomUUID(),sequence:1,frame:null,issuedAt:Date.now(),expiresAt:Date.now()+950};
  async function submit(value,wrong=false){const raw=Buffer.from(JSON.stringify(value)),body=JSON.stringify({payloadBase64url:raw.toString('base64url'),signatureBase64url:wrong?'A'.repeat(86):sign(null,raw,await f.pem('device.key')).toString('base64url')});
    const options={method:'POST',key:await f.pem('device.key'),cert:await f.pem('device.pem'),ca:await f.pem('ca.pem'),headers:{'content-type':'application/json'}};
    return new Promise((resolve,reject)=>{const request=https.request(f.url.replace('wss:','https:').replace('/edge/v1/connect','/edge/v1/media-grant'),options,response=>{let text='';response.on('data',chunk=>text+=chunk);response.on('end',()=>resolve({status:response.statusCode,body:JSON.parse(text)}));});request.on('error',reject);request.end(body);});}
  assert.equal((await submit(report,true)).status,403);assert.equal(accepted.length,0);
  assert.equal((await submit({...report,context:{...context,connectionId:randomUUID()}})).status,403);assert.equal(accepted.length,0);
  const result=await submit(report);assert.equal(result.status,200);assert.ok(result.body.envelope);assert.equal(accepted.length,1);assert.equal(f.relay.devices.get(f.identity.id).controlAccepted,false);assert.equal(context.executorEpoch,null);
});

test('Python bound transport forwards signed lease and journaled command once without implicit SDK connect',async t=>{
  const f=await fixture(t,{control:true}),keys=generateKeyPairSync('ed25519'),signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey});
  const input={url:f.url,device_id:f.identity.id,boot_id:randomUUID(),certificate:path.join(f.dir,'device.pem'),private_key:path.join(f.dir,'device.key'),ca_file:path.join(f.dir,'ca.pem'),heartbeat_seconds:0.1};
  const executorEpoch=randomUUID();
  const script=`import asyncio,json,sys\nfrom pathlib import Path\nfrom websockets.exceptions import ConnectionClosed\nfrom thirdhand_edge.transport import DeviceConfig\nfrom thirdhand_edge.bound_transport import connect_bound_device\nfrom thirdhand_edge.journal import CommandJournal\nv=json.load(sys.stdin)\nclass FakeRobot:\n def __init__(self): self.calls=[]\n async def get_context(self): return {'deviceId':v['config']['device_id'],'executorEpoch':v['executorEpoch'],'hardwareFingerprint':'f'*64,'controlAccepted':True}\n async def bind(self,c): return {'bound':True,'context':c,'controlAuthorized':False}\n async def submit_envelope(self,p):\n  self.calls.append(p['purpose'])\n  if p['purpose'].startswith('lease_'): return {'state':'active','leaseId':p['leaseId'],'leaseEpoch':p['leaseEpoch']}\n  return {'state':'completed','commandId':p['commandId']}\nr=FakeRobot()\nj=CommandJournal(v['journal'])\ntry: asyncio.run(connect_bound_device(DeviceConfig(**v['config']),robot=r,trusted_keys={'test':v['publicKey']},journal=j))\nexcept ConnectionClosed: pass\nfinally:\n j.close()\n print(json.dumps({'calls':r.calls}))`;
  const child=require('node:child_process').spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});
  f.track(child);
  let stdout='',stderr='';child.stdout.on('data',v=>stdout+=v);child.stderr.on('data',v=>stderr+=v);
  const bound=once(f.relay.devices.events,'bound',{signal:AbortSignal.timeout(5000)});
  child.stdin.end(JSON.stringify({config:input,executorEpoch,journal:path.join(f.dir,'bound.sqlite'),publicKey:keys.publicKey.export({type:'spki',format:'pem'}).toString()}));
  await bound;
  const binding=f.relay.devices.get(f.identity.id),context=Object.fromEntries(['deviceId','bootId','executorEpoch','connectionId','certificateId'].map(key=>[key,binding[key]]));
  const leaseId=randomUUID(),now=Date.now();
  assert.equal((await f.relay.devices.request(f.identity.id,signer.sign({schema:1,purpose:'lease_grant',...context,leaseId,leaseEpoch:1,sequence:0,issuedAt:now,expiresAt:now+1000}))).state,'active');
  const command=signer.sign({schema:1,purpose:'command',...context,leaseId,leaseEpoch:1,sequence:1,commandId:randomUUID(),opcode:'connect',parameters:{},issuedAt:Date.now(),expiresAt:Date.now()+1000});
  assert.equal((await f.relay.devices.request(f.identity.id,command)).state,'completed');
  assert.equal((await f.relay.devices.request(f.identity.id,command)).state,'completed');
  const exited=once(child,'close');await f.relay.close();assert.equal((await exited)[0],0,stderr);
  assert.deepEqual(JSON.parse(stdout).calls,['lease_grant','command']);
});

test('bounded probe CLI measures sustained ping and planned reconnects without printing credentials',async t=>{
  const f=await fixture(t),configPath=path.join(f.dir,'probe.toml');
  const values={url:f.url,device_id:f.identity.id,certificate:path.join(f.dir,'device.pem'),private_key:path.join(f.dir,'device.key'),ca_file:path.join(f.dir,'ca.pem')};
  await fs.writeFile(configPath,Object.entries(values).map(([k,v])=>`${k} = ${JSON.stringify(v)}`).join('\n'));
  const output=await run(python,['-m','thirdhand_edge.probe','--config',configPath,'--duration-seconds','1','--cycles','2'],
    {env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},timeout:15000});
  const report=JSON.parse(output.stdout);
  assert.equal(report.completed,true);assert.equal(report.completedCycles,2);assert.equal(report.uniqueConnections,2);
  assert.equal(report.controlAuthorized,false);assert.ok(report.elapsedSeconds>=1);assert.ok(report.measurements.samples>=2);
  assert.ok(report.measurements.rttMs.p99>=report.measurements.rttMs.p50);
  for(const secret of [f.identity.id,f.url,configPath,'BEGIN PRIVATE KEY'])assert.equal(output.stdout.includes(secret),false);
});

test('unknown certificate, foreign device, browser cookie and forged proxy headers cannot become device identity',async t=>{
  const f=await fixture(t);
  await assert.rejects(f.socket('unknown'));
  await assert.rejects(f.socket('device',{headers:{Cookie:'user=admin','X-SSL-Client-Verify':'SUCCESS','X-SSL-Client-Cert':encodeURIComponent((await f.pem('device.pem')).toString())}}));
  const ws=await f.socket(), closed=once(ws,'close');
  ws.send(JSON.stringify({type:'hello',protocol:1,deviceId:randomUUID(),bootId:randomUUID(),executorEpoch:null,agentVersion:'0.1.0',capabilities:['probe']}));
  await closed;assert.equal(f.relay.devices.get(f.identity.id),null);
});

test('wrong private key cannot finish proof even with a valid public certificate',async t=>{
  const f=await fixture(t), ws=await f.socket(), closed=once(ws,'close');
  const attempt=assert.rejects(f.auth(ws,{signer:'unknown'}));
  await closed;await attempt;assert.equal(f.relay.devices.get(f.identity.id),null);
});

test('credential rebind cannot preserve an existing channel under the previous device',async t=>{
  const f=await fixture(t),ws=await f.socket();await f.auth(ws);f.rebind();
  const next=Promise.race([nextMessage(ws).then(()=> 'pong',()=> 'closed'),new Promise(resolve=>setTimeout(()=>resolve('timeout'),3000))]);
  ws.send(JSON.stringify({type:'ping',nonce:'after-rebind'}));
  assert.equal(await next,'closed');
});

test('TCP forwarded-certificate headers cannot access the private Unix proxy ingress',async t=>{
  const relay=createDeviceRelay({trustedUnixProxy:true,store:{async resolveCertificate(){throw Error('must not reach registry');}}});
  await new Promise(resolve=>relay.server.listen(0,'127.0.0.1',resolve));t.after(()=>relay.close());
  const response=await fetch(`http://127.0.0.1:${relay.server.address().port}/edge/v1/healthz`,{headers:{'X-SSL-Client-Verify':'SUCCESS','X-SSL-Client-Cert':'fake'}});
  assert.equal(response.status,403);
});

test('Python outbound client validates the test CA and completes two-way no-hardware heartbeat',async t=>{
  const f=await fixture(t);
  const script=`import asyncio,json,sys\nfrom pathlib import Path\nfrom thirdhand_edge.transport import DeviceConfig,connect_device\nv=json.load(sys.stdin)\nc=DeviceConfig(**v)\nr=asyncio.run(connect_device(c,probe_count=2))\nassert r['controlAuthorized'] is False\nprint(json.dumps(r))`;
  const input={url:f.url,device_id:f.identity.id,boot_id:randomUUID(),certificate:path.join(f.dir,'device.pem'),private_key:path.join(f.dir,'device.key'),ca_file:path.join(f.dir,'ca.pem'),heartbeat_seconds:0.1};
  async function probe(data){
    const child=require('node:child_process').spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});
    let stdout='',stderr='';child.stdout.on('data',x=>stdout+=x);child.stderr.on('data',x=>stderr+=x);child.stdin.end(JSON.stringify(data));
    return {code:(await once(child,'close'))[0],stdout,stderr};
  }
  const good=await probe(input);assert.equal(good.code,0,good.stderr);assert.equal(JSON.parse(good.stdout).heartbeats,2);
  const metrics=JSON.parse(good.stdout).measurements;
  assert.equal(metrics.samples,2);assert.ok(metrics.rttMs.p99>=metrics.rttMs.p50);assert.ok(metrics.rttMs.min>=0);
  const untrusted=await probe({...input,ca_file:null});assert.notEqual(untrusted.code,0);assert.match(untrusted.stderr,/CERTIFICATE_VERIFY_FAILED/);
});

test('Node envelope is verified by Python over the identical bytes and key alias tampering fails',async t=>{
  const keys=generateKeyPairSync('ed25519'), signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey});
  const binding={deviceId:'a',bootId:'b',executorEpoch:null,connectionId:'c'};
  const envelope=signer.sign({schema:1,purpose:'probe',...binding,issuedAt:1000,expiresAt:2000,number:0.1234567890123});
  const script=`import sys,json\nfrom thirdhand_edge.protocol import verify_envelope,ProtocolError\nv=json.load(sys.stdin)\np=verify_envelope(v['envelope'],v['keys'],v['binding'],now_ms=1500)\nassert p['number']==0.1234567890123\nv['envelope']['keyId']='alias'\ntry: verify_envelope(v['envelope'],v['keys'],v['binding'],now_ms=1500)\nexcept ProtocolError: print('verified')\nelse: raise AssertionError('alias accepted')`;
  const input={envelope,binding,keys:{test:keys.publicKey.export({format:'pem',type:'spki'}).toString(),alias:keys.publicKey.export({format:'pem',type:'spki'}).toString()}};
  const child=require('node:child_process').spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});
  t.after(()=>{if(child.exitCode===null&&child.signalCode===null)child.kill();});
  let stdout='',stderr='';child.stdout.on('data',x=>stdout+=x);child.stderr.on('data',x=>stderr+=x);child.stdin.end(JSON.stringify(input));
  assert.equal((await once(child,'close'))[0],0,stderr);assert.match(stdout,/verified/);
});

test('telemetry uses a separate mTLS HTTP request and signed exact batch bytes; invalid signature is not ACKed',async t=>{
  const accepted=[];let committed=false;const f=await fixture(t,{ingestBatch:async(context,batch)=>{accepted.push({context,batch});return {batchId:batch.batchId,digest:batch.digest,persisted:committed};}});
  const batchId=randomUUID(),raw=Buffer.from(JSON.stringify({deviceId:f.identity.id,bootId:randomUUID(),batchId,rows:[]}));
  const envelope={batchId,digest:require('node:crypto').createHash('sha256').update(raw).digest('hex'),payloadBase64url:raw.toString('base64url'),signatureBase64url:sign(null,raw,await f.pem('device.key')).toString('base64url')};
  async function upload(value){
    const body=JSON.stringify(value),options={method:'POST',key:await f.pem('device.key'),cert:await f.pem('device.pem'),ca:await f.pem('ca.pem'),headers:{'content-type':'application/json','content-length':Buffer.byteLength(body)}};
    return new Promise((resolve,reject)=>{const request=https.request(f.url.replace('wss:','https:').replace('/edge/v1/connect','/edge/v1/telemetry-batches'),options,response=>{let data='';response.on('data',value=>data+=value);response.on('end',()=>resolve({status:response.statusCode,body:JSON.parse(data)}));});request.on('error',reject);request.end(body);});
  }
  assert.equal((await upload({...envelope,signatureBase64url:'A'.repeat(86)})).status,403);assert.equal(accepted.length,0);
  const unavailable=await upload(envelope);assert.equal(unavailable.status,503);assert.equal(unavailable.body.persisted,undefined);
  committed=true;
  const result=await upload(envelope);assert.equal(result.status,200);assert.equal(result.body.persisted,true);assert.equal(accepted.length,2);assert.equal(accepted[0].context.deviceId,f.identity.id);
  assert.equal(f.relay.devices.get(f.identity.id),null,'telemetry upload must not occupy or establish control channel');
});

test('Python immutable outbox upload is signed and only a matching committed HTTPS ACK clears pending',async t=>{
  const accepted=[];const f=await fixture(t,{ingestBatch:async(context,batch)=>{accepted.push({context,batch});return {batchId:batch.batchId,digest:batch.digest,persisted:true};}});
  const config={url:f.url,device_id:f.identity.id,boot_id:randomUUID(),certificate:path.join(f.dir,'device.pem'),private_key:path.join(f.dir,'device.key'),ca_file:path.join(f.dir,'ca.pem')};
  const script=`import asyncio,json,sys\nfrom thirdhand_edge.transport import DeviceConfig\nfrom thirdhand_edge.outbox import Outbox\nfrom thirdhand_edge.upload import upload_pending\nv=json.load(sys.stdin)\nc=DeviceConfig(**v['config'])\nb=Outbox(v['database'],device_id=c.device_id,boot_id=c.boot_id)\nfor n in range(2): b.append_sample({'capturedAt':'2026-10-30T09:00:00.000Z','monotonicNs':str(n),'clockQuality':'estimated','jointPositionRad':[0,1.57,-1.57,0,0,0],'sdkConnected':False,'moving':False,'extra':{}})\nb.seal_batch('robot_samples')\nr=asyncio.run(upload_pending(c,b))\nassert r=={'acknowledged':1},r\nassert b.pending_batches()==[]\nb.close()\nprint('upload-committed')`;
  const child=require('node:child_process').spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});
  f.track(child);
  let stdout='',stderr='';child.stdout.on('data',x=>stdout+=x);child.stderr.on('data',x=>stderr+=x);child.stdin.end(JSON.stringify({config,database:path.join(f.dir,'upload.sqlite')}));
  assert.equal((await once(child,'close'))[0],0,stderr);assert.match(stdout,/upload-committed/);assert.equal(accepted.length,1);
  const payload=JSON.parse(Buffer.from(accepted[0].batch.payloadBase64url,'base64url'));assert.equal(payload.rows.length,2);
});

test('Python outbox to mTLS ingress to real PostgreSQL commits every sample and exact payload before ACK',async t=>{
  const db=await require('./identity-fixture').identityFixture(t);db.clock.value=Date.now();
  const repository=require('../../../platform/storage/src/ingest').createIngestRepository(db.pool,{clock:db.clock});
  const f=await fixture(t,{ingestBatch:(context,batch)=>repository.ingestBatch(context,batch)});
  const certificate=new X509Certificate(await f.pem('device.pem'));
  await db.pool.query("INSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities) VALUES($1,'mTLS synthetic test',$3,true,$2)",[f.identity.id,{deviceClass:'synthetic'},f.identity.id]);
  await db.pool.query('INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7)',[f.identity.certificateId,f.identity.id,certificate.serialNumber,f.identity.fingerprint,certificate.publicKey.export({type:'spki',format:'pem'}),certificate.validFromDate,certificate.validToDate]);
  await db.pool.query('SELECT telemetry.ensure_month_partition($1::date)',[db.clock.now().toISOString().slice(0,7)+'-01']);
  const config={url:f.url,device_id:f.identity.id,boot_id:randomUUID(),certificate:path.join(f.dir,'device.pem'),private_key:path.join(f.dir,'device.key'),ca_file:path.join(f.dir,'ca.pem')};
  const script=`import asyncio,json,sys\nfrom thirdhand_edge.transport import DeviceConfig\nfrom thirdhand_edge.outbox import Outbox\nfrom thirdhand_edge.upload import upload_pending\nv=json.load(sys.stdin)\nc=DeviceConfig(**v['config'])\nb=Outbox(v['database'],device_id=c.device_id,boot_id=c.boot_id)\nfor n in range(2): b.append_sample({'capturedAt':v['capturedAt'],'monotonicNs':str(100+n),'clockQuality':'estimated','jointPositionRad':[0,1.57,-1.57,0,0,0],'sdkConnected':False,'moving':False,'extra':{'synthetic':True,'sourceMode':'simulation'}})\nb.seal_batch('robot_samples')\nr=asyncio.run(upload_pending(c,b))\nassert r=={'acknowledged':1},r\nassert b.pending_batches()==[]\nb.close()\nprint('full-upload-committed')`;
  const child=f.track(require('node:child_process').spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']}));
  let stdout='',stderr='';child.stdout.on('data',x=>stdout+=x);child.stderr.on('data',x=>stderr+=x);child.stdin.end(JSON.stringify({config,database:path.join(f.dir,'pg-upload.sqlite'),capturedAt:db.clock.now().toISOString()}));
  assert.equal((await once(child,'close'))[0],0,stderr);assert.match(stdout,/full-upload-committed/);
  assert.equal((await db.pool.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count,'2');
  const stored=(await db.pool.query('SELECT b.digest,p.payload_bytes FROM telemetry.ingest_batches b JOIN telemetry.ingest_batch_payloads p ON p.batch_id=b.id')).rows[0];
  assert.equal(require('node:crypto').createHash('sha256').update(stored.payload_bytes).digest('hex'),stored.digest);
});
