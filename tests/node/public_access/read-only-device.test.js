'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomUUID,randomBytes,generateKeyPairSync}=require('node:crypto');
const {EventEmitter}=require('node:events');
const {createRemoteRobotGateway}=require('../../../services/robot/src/remote-gateway');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');
test('unattended read-only gateway allows explicit SDK connect, rejects all motion and disconnects on lease loss',async t=>{
  class ReadController extends EventEmitter{
    constructor(){super();this.config={simulate:false};this.bridge=new EventEmitter();this.bridge.child={pid:123};this.calls=[];}
    handleCommand(command){this.calls.push(command.cmd);if(['connect','disconnect'].includes(command.cmd)){this.bridge.connected=command.cmd==='connect';this.emit('message',{type:'connection',connected:this.bridge.connected,request_id:command.request_id,sdk_released:!this.bridge.connected});}}
  }
  const controller=new ReadController(),keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID();
  const gateway=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]]),readOnly:true});
  const server=require('node:http').createServer((q,s)=>gateway.handle(q,s));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const post=(route,body)=>fetch(base+route,{method:'POST',headers,body:JSON.stringify(body)});
  const snapshot=await fetch(base+'context',{headers}).then(r=>r.json());assert.equal(snapshot.bindingAccepted,true);assert.equal(snapshot.controlAccepted,false);assert.deepEqual(controller.calls,[]);
  const context={deviceId,bootId:randomUUID(),executorEpoch:snapshot.executorEpoch,connectionId:randomUUID(),certificateId:randomUUID()};await post('bind',context);
  const source=await fetch(base+'events',{headers}),reader=source.body.getReader();await reader.read();
  await post('capture-health',{bootId:context.bootId,executorEpoch:context.executorEpoch,writable:true,sourceSequence:0});
  const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey}),leaseId=randomUUID();
  const stamp=()=>({issuedAt:Date.now(),expiresAt:Date.now()+500});
  const grant={schema:1,...context,purpose:'lease_grant',leaseId,leaseEpoch:1,sequence:0,...stamp()};
  assert.equal((await (await post('envelope',signer.sign(grant))).json()).state,'active');
  const command={schema:1,...context,purpose:'command',leaseId,leaseEpoch:1,sequence:1,commandId:randomUUID(),opcode:'connect',parameters:{},...stamp()};
  assert.equal((await (await post('envelope',signer.sign(command))).json()).state,'completed');
  for(const [opcode,parameters]of [['move_joint',{joints:[0,0,0,0,0,1]}],['preset',{name:'home'}],['gripper',{position:1}]]){
    const response=await post('envelope',signer.sign({...command,commandId:randomUUID(),sequence:2,opcode,parameters,...stamp()}));assert.equal(response.status,403);
  }
  await new Promise(resolve=>setTimeout(resolve,650));
  assert.deepEqual(controller.calls,['connect','disconnect']);assert.equal(controller.bridge.connected,false);await reader.cancel();
});
test('cloud read-only veto occurs before recording or submitting any movement command',async t=>{
  const f=await require('./control-fixture').controlFixture(t);f.context.readOnly=true;const browser=f.browser(f.first),lease=await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  await assert.rejects(f.service.dispatchRealCommand(f.first,{deviceId:f.deviceId,...browser,leaseId:lease.id,commandId:randomUUID(),opcode:'move_joint',parameters:{joints:[0,0,0,0,0,1]}}),{code:'READ_ONLY_DEVICE'});
  assert.equal(f.requests.filter(x=>x.purpose==='command').length,0);assert.equal((await f.pool.query('SELECT count(*) FROM ops.commands')).rows[0].count,'0');
});
test('lease storage independently refuses a credential without explicit SDK enrollment',async t=>{
  const f=await require('./control-fixture').controlFixture(t),browser=f.browser(f.first);
  await f.pool.query('UPDATE ops.device_credentials SET control_enabled=false WHERE id=$1',[f.context.certificateId]);
  await assert.rejects(f.repo.reserve(f.first,{context:f.context,...browser}),{code:'DEVICE_UNAVAILABLE'});
});
test('revocation during SDK initialization waits for a queued disconnect instead of releasing a pending connect',async t=>{
  class DelayedController extends EventEmitter{
    constructor(){super();this.config={simulate:false};this.bridge=new EventEmitter();this.bridge.child={pid:124};this.calls=[];this.queue=Promise.resolve();}
    handleCommand(command){this.calls.push(command.cmd);this.queue=this.queue.then(async()=>{if(command.cmd==='connect')await new Promise(resolve=>setTimeout(resolve,180));this.bridge.connected=command.cmd==='connect';this.emit('message',{type:'connection',connected:this.bridge.connected,request_id:command.request_id,sdk_released:!this.bridge.connected});});this.emit('submitted');}
  }
  const controller=new DelayedController(),keys=generateKeyPairSync('ed25519'),token=randomBytes(32).toString('hex'),deviceId=randomUUID();
  const gateway=createRemoteRobotGateway({controller,deviceId,token,signingKeys:new Map([['test',keys.publicKey]]),readOnly:true});
  const server=require('node:http').createServer((q,s)=>gateway.handle(q,s));await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const post=(route,body)=>fetch(base+route,{method:'POST',headers,body:JSON.stringify(body)}).then(r=>r.json());
  const snapshot=await fetch(base+'context',{headers}).then(r=>r.json()),context={deviceId,bootId:randomUUID(),executorEpoch:snapshot.executorEpoch,connectionId:randomUUID(),certificateId:randomUUID()};await post('bind',context);
  const source=await fetch(base+'events',{headers}),reader=source.body.getReader();await reader.read();await post('capture-health',{bootId:context.bootId,executorEpoch:context.executorEpoch,writable:true,sourceSequence:0});
  const signer=createEnvelopeSigner({keyId:'test',privateKey:keys.privateKey}),leaseId=randomUUID(),stamp=()=>({issuedAt:Date.now(),expiresAt:Date.now()+950});
  await post('envelope',signer.sign({schema:1,...context,purpose:'lease_grant',leaseId,leaseEpoch:1,sequence:0,...stamp()}));
  const submitted=require('node:events').once(controller,'submitted');
  const connecting=post('envelope',signer.sign({schema:1,...context,purpose:'command',leaseId,leaseEpoch:1,sequence:1,commandId:randomUUID(),opcode:'connect',parameters:{},...stamp()}));await submitted;
  const result=await post('envelope',signer.sign({schema:1,...context,purpose:'stop',leaseId:null,leaseEpoch:0,sequence:0,commandId:randomUUID(),opcode:'software_stop',parameters:{},...stamp()}));
  await connecting;await controller.queue;
  assert.equal(result.state,'stopped');assert.equal(controller.bridge.connected,false);assert.deepEqual(controller.calls,['connect','disconnect']);await reader.cancel();
});
