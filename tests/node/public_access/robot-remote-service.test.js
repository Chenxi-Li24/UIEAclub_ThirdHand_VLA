'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter,once}=require('node:events');
const {spawn}=require('node:child_process');
const {generateKeyPairSync,randomUUID,randomBytes}=require('node:crypto');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {WebSocket}=require('ws');
const {createRobotService}=require('../../../services/robot/src/server');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');
const {createRemoteRobotGateway}=require('../../../services/robot/src/remote-gateway');

class FakeController extends EventEmitter{
  constructor(){super();this.calls=[];this.config={simulate:true,canInterface:'fake-can'};this.bridge=new EventEmitter();this.bridge.child={pid:123};this.bridge.armRemoteLease=()=>true;this.bridge.renewRemoteLease=()=>true;this.bridge.revokeRemoteLease=()=>true;this.latestRobotStateAtMs=Date.now();this.stateReady=true;}
  async start(){} async shutdown(){} health(){return {status:'ready',robot:{connected:false}};}configMessage(){return {type:'config'};}
  handleCommand(command,reply){this.calls.push(command);if(command.cmd==='software_stop'){this.bridge.connected=false;this.emit('message',{type:'command_status',request_id:command.request_id,status:'complete',stopped:true});}else if(command.cmd==='connect'){this.bridge.connected=true;this.emit('message',{type:'connection',connected:true});}else this.emit('message',{type:'command_status',request_id:command.request_id,status:'complete',reached:true});}
}

test('remote service blocks all legacy mutation paths and verifies signed local envelopes before FakeRobot',async t=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-remote-'));
  t.after(async()=>{const checked=path.resolve(directory);assert.equal(path.dirname(checked),path.resolve(os.tmpdir()));assert.ok(path.basename(checked).startsWith('thirdhand-remote-'));await fs.rm(checked,{recursive:true,force:true});});
  const controller=new FakeController(),keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID();
  const service=createRobotService({host:'127.0.0.1',port:0,readyFile:path.join(directory,'ready'),robot:controller.config,remote:{enabled:true,deviceId},controller,edgeToken:token,cloudSigningKeys:new Map([['test',keys.publicKey]])});
  t.after(()=>service.close());const address=await service.start(),base=`http://127.0.0.1:${address.port}`;
  const headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  assert.equal((await fetch(base+'/edge-control/v1/context')).status,403);
  const snapshot=await fetch(base+'/edge-control/v1/context',{headers}).then(r=>r.json());
  assert.equal(controller.calls.length,0);assert.equal(snapshot.sdkConnected,false);
  for(const endpoint of ['/ws','/execution','/meituan']){
    const socket=new WebSocket(`ws://127.0.0.1:${address.port}${endpoint}`,{headers:{'x-thirdhand-execution-token':token,'x-thirdhand-meituan-token':token}});
    await assert.rejects(once(socket,'open'));assert.equal(controller.calls.length,0);
  }
  const context={deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch:snapshot.executorEpoch};
  const post=(route,value)=>fetch(base+'/edge-control/v1/'+route,{method:'POST',headers,body:JSON.stringify(value)});
  assert.equal((await post('bind',context)).status,200);
  const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey});
  const stamp=()=>({issuedAt:Date.now(),expiresAt:Date.now()+950});
  const leaseId=randomUUID();
  const grant={schema:1,...context,purpose:'lease_grant',leaseId,leaseEpoch:1,sequence:0,...stamp()};
  assert.equal((await (await post('envelope',signer.sign(grant))).json()).state,'active');
  const command={schema:1,...context,purpose:'command',commandId:randomUUID(),leaseId,leaseEpoch:1,sequence:1,opcode:'connect',parameters:{},...stamp()};
  const signed=signer.sign(command);
  assert.equal((await post('envelope',{...signed,signatureBase64url:'A'.repeat(86)})).status,403);assert.equal(controller.calls.length,0);
  assert.equal((await (await post('envelope',signed)).json()).state,'completed');assert.equal(controller.calls.length,1);
  const tokenFile=path.join(directory,'edge-token');await fs.writeFile(tokenFile,token,{mode:0o600});
  const next=signer.sign({...command,commandId:randomUUID(),sequence:2,opcode:'disconnect',...stamp()});
  const input={base,tokenFile,context,envelope:next,publicKey:keys.publicKey.export({format:'pem',type:'spki'}).toString(),journal:path.join(directory,'agent-journal.sqlite')};
  const script=`import sys,json,asyncio\nfrom thirdhand_edge.robot_client import RobotClient\nfrom thirdhand_edge.command_gate import CommandGate\nfrom thirdhand_edge.journal import CommandJournal\nv=json.load(sys.stdin)\nr=RobotClient(base_url=v['base'],token_file=v['tokenFile'])\nj=CommandJournal(v['journal'])\ng=CommandGate(trusted_keys={'test':v['publicKey']},journal=j,robot=r,clock=lambda:__import__('time').time_ns()//1000000)\nasync def run():\n assert (await r.get_context())['controlAccepted'] is True\n a=await g.handle_envelope(v['envelope'],v['context'])\n b=await g.handle_envelope(v['envelope'],v['context'])\n assert a==b and a['state']=='stopped',a\n print('agent-completed-once')\nasyncio.run(run())\nj.close()`;
  const child=spawn(process.env.EDGE_TEST_PYTHON||'python',['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});
  let stderr='',stdout='';child.stderr.on('data',x=>stderr+=x);child.stdout.on('data',x=>stdout+=x);child.stdin.end(JSON.stringify(input));
  assert.equal((await once(child,'close'))[0],0,stderr);assert.match(stdout,/agent-completed-once/);assert.equal(controller.calls.length,2);
  controller.bridge.child={pid:456};
  assert.equal((await (await post('envelope',signer.sign({...command,commandId:randomUUID(),sequence:3,...stamp()}))).json()).state,'rejected');
  assert.ok(controller.calls.some(value=>value.cmd==='software_stop'));
});

test('confirmed priority stop settles an in-flight ordinary command and allows a fresh binding without resuming it',async t=>{
  let entered;const started=new Promise(resolve=>entered=resolve);
  class BlockingFake extends FakeController{handleCommand(command,reply){if(command.cmd==='move_joint'){this.calls.push(command);entered();return;}super.handleCommand(command,reply);}}
  const controller=new BlockingFake(),keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID(),gateway=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]])});
  const server=require('node:http').createServer((request,response)=>gateway.handle(request,response));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const post=(route,body)=>fetch(base+route,{method:'POST',headers,body:JSON.stringify(body)}).then(r=>r.json());
  const bootId=randomUUID(),snapshot=await post('prepare-binding',{bootId}),context={deviceId,bootId,executorEpoch:snapshot.executorEpoch,connectionId:randomUUID(),certificateId:randomUUID()};
  await post('bind',context);const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey}),stamp=()=>({issuedAt:Date.now(),expiresAt:Date.now()+950}),leaseId=randomUUID();
  await post('envelope',signer.sign({schema:1,...context,purpose:'lease_grant',leaseId,leaseEpoch:1,sequence:0,...stamp()}));
  const moving=post('envelope',signer.sign({schema:1,...context,purpose:'command',commandId:randomUUID(),leaseId,leaseEpoch:1,sequence:1,opcode:'move_joint',parameters:{joints:[0,90,-90,0,0,0]},...stamp()}));
  await started;
  const stopped=await post('envelope',signer.sign({schema:1,...context,purpose:'stop',commandId:randomUUID(),leaseId:null,leaseEpoch:0,sequence:0,opcode:'software_stop',parameters:{},...stamp()}));assert.equal(stopped.state,'stopped');
  const outcome=await Promise.race([moving,new Promise(resolve=>setTimeout(()=>resolve({state:'timeout'}),500))]);assert.equal(outcome.state,'stopped');
  const nextBoot=randomUUID(),prepared=await post('prepare-binding',{bootId:nextBoot});assert.notEqual(prepared.executorEpoch,context.executorEpoch);
  const bound=await post('bind',{...context,bootId:nextBoot,executorEpoch:prepared.executorEpoch,connectionId:randomUUID()});
  assert.equal(bound.previousStop.state,'stopped');assert.equal(bound.previousStop.leaseId,leaseId);assert.equal(bound.previousStop.executorEpoch,context.executorEpoch);assert.equal(controller.calls.filter(value=>value.cmd==='move_joint').length,1);
});

test('physical controller rejects a correctly signed grant without onsite evidence and does not auto-connect',async t=>{
  const controller=new FakeController();controller.config.simulate=false;
  const keys=generateKeyPairSync('ed25519'),deviceId=randomUUID(),gateway=createRemoteRobotGateway({controller,deviceId,token:randomBytes(32).toString('hex'),signingKeys:new Map([['test',keys.publicKey]])});
  const token=randomBytes(32).toString('hex');await gateway.close();
  const physical=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]])});
  const server=require('node:http').createServer((request,response)=>physical.handle(request,response));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await physical.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const snapshot=await fetch(base+'context',{headers}).then(r=>r.json());assert.equal(snapshot.controlAccepted,false);
  const context={deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch:snapshot.executorEpoch};
  await fetch(base+'bind',{method:'POST',headers,body:JSON.stringify(context)});
  const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey});
  const grant=signer.sign({schema:1,...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:Date.now(),expiresAt:Date.now()+950});
  const response=await fetch(base+'envelope',{method:'POST',headers,body:JSON.stringify(grant)});
  assert.equal(response.status,409);assert.equal((await response.json()).code,'HARDWARE_ACCEPTANCE_REQUIRED');assert.equal(controller.calls.length,0);
});

test('private source subscription preserves each measured event and never connects the SDK',async t=>{
  const controller=new FakeController(),keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID();
  const gateway=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]])});
  const server=require('node:http').createServer((request,response)=>gateway.handle(request,response));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const response=await fetch(`http://127.0.0.1:${server.address().port}/edge-control/v1/events`,{headers:{'x-thirdhand-edge-token':token}});
  assert.equal(response.status,200);assert.match(response.headers.get('content-type'),/text\/event-stream/);
  const reader=response.body.getReader(),decoder=new TextDecoder();const first=decoder.decode((await reader.read()).value);assert.match(first,/source_snapshot/);assert.equal(controller.calls.length,0);
  const raw={type:'robot_state',ts:Date.now(),joints_deg:[1,2,-3,4,5,6],connected:true,moving:false};
  controller.emit('message',raw);
  const frame=decoder.decode((await reader.read()).value);const data=JSON.parse(frame.split('\n').find(line=>line.startsWith('data: ')).slice(6));
  assert.deepEqual(data.message,raw);assert.equal(data.sequence,1);assert.equal(controller.calls.length,0);
  await reader.cancel();
});

test('capture backlog, disk veto or a lost capture stream revokes the physical-mode fake lease independently of Agent control',async t=>{
  const controller=new FakeController();controller.config.simulate=false;
  const keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID();let monotonic=0;
  const syntheticStopProfile={digest:'b'.repeat(64),stop:{maxStopTimeMs:1000,maxFeedbackAgeMs:200,maxVelocityRadS:0.01,maxJointDeltaDeg:0.2,minStableDurationMs:100,minSamples:3,requiresDisabled:false,includesGripper:false}};
  const gateway=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]]),clock:{now:()=>Date.now(),monotonic:()=>monotonic},hardwareAccepted:()=>true,initialStopVerified:()=>true,
    nativeStopSupported:true,stopProfile:syntheticStopProfile,requestControlledStop:operation=>controller.handleCommand({cmd:'software_stop',request_id:operation.commandId})});
  const server=require('node:http').createServer((request,response)=>gateway.handle(request,response));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const post=(route,body)=>fetch(base+route,{method:'POST',headers,body:JSON.stringify(body)}).then(r=>r.json());
  const snapshot=await fetch(base+'context',{headers}).then(r=>r.json()),context={deviceId,bootId:randomUUID(),executorEpoch:snapshot.executorEpoch,certificateId:randomUUID(),connectionId:randomUUID()};
  await post('bind',context);const source=await fetch(base+'events',{headers}),reader=source.body.getReader();await reader.read();assert.equal(controller.calls.length,0);
  const health=writable=>post('capture-health',{bootId:context.bootId,executorEpoch:context.executorEpoch,writable,sourceSequence:0});
  const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey}),leaseId=randomUUID(),publisherId=randomUUID();let mediaSequence=0;
  const media=frameId=>post('media-health',signer.sign({schema:1,...context,purpose:'media_publish',publisherId,sequence:++mediaSequence,sourceFresh:true,frame:{frameId,capturedAtUs:String(BigInt(Date.now())*1000n),clockQuality:'synchronized',uncertaintyMs:1},issuedAt:Date.now(),expiresAt:Date.now()+950}));
  await health(true);assert.equal((await fetch(base+'context',{headers}).then(r=>r.json())).controlAccepted,false);
  await media('1');assert.equal((await fetch(base+'context',{headers}).then(r=>r.json())).controlAccepted,true);
  const grant=()=>signer.sign({schema:1,...context,purpose:'lease_grant',leaseId,leaseEpoch:1,sequence:0,issuedAt:Date.now(),expiresAt:Date.now()+950});
  assert.equal((await post('envelope',grant())).state,'active');
  controller.emit('message',{type:'robot_state',joints_deg:[0,90,-90,0,0,0],ts:Date.now(),connected:false,moving:false});
  monotonic=1100;await health(true);await media('2'); // video is fresh; durable capture cursor is behind.
  assert.equal((await fetch(base+'context',{headers}).then(r=>r.json())).controlAccepted,false);
  await new Promise(resolve=>setTimeout(resolve,80));assert.equal(gateway.policy.currentLease(),null);
  const state=await fetch(base+'context',{headers}).then(r=>r.json());
  await post('capture-health',{bootId:context.bootId,executorEpoch:context.executorEpoch,writable:false,sourceSequence:state.sourceSequence});
  assert.equal((await fetch(base+'context',{headers}).then(r=>r.json())).controlAccepted,false);
  await reader.cancel();assert.equal(controller.calls.filter(call=>call.cmd==='connect').length,0);
});
