'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {EventEmitter}=require('node:events');
const {generateKeyPairSync,randomUUID,randomBytes}=require('node:crypto');
const {createRemoteRobotGateway}=require('../../../services/robot/src/remote-gateway');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');

async function fixture(t,{readOnly=false,release=true,releaseRequestId,receipt=null,getStopEvidence,stopProfile}={}){
  const controller=new EventEmitter();controller.config={simulate:false,canInterface:'test-can'};
  controller.bridge=new EventEmitter();controller.bridge.child={pid:1};controller.bridge.connected=true;
  controller.stateReady=false;controller.calls=[];const outcomes=[];
  controller.on('message',message=>{if(message.type==='remote_command_outcome')outcomes.push(message);});
  controller.handleCommand=command=>{controller.calls.push(command);
    if(command.cmd==='disconnect')controller.emit('message',{type:'connection',connected:false,request_id:releaseRequestId||command.request_id,
      sdk_released:release,cleanup_state:release?'completed':'failed'});
    else controller.emit('message',{type:'command_status',request_id:command.request_id,
      status:'complete',stopped:true,...receipt});};
  const token=randomBytes(32).toString('hex'),deviceId=randomUUID(),keys=generateKeyPairSync('ed25519');
  const gateway=createRemoteRobotGateway({controller,deviceId,token,readOnly,
    signingKeys:new Map([['stop-test',keys.publicKey]]),getStopEvidence,stopProfile,stopTimeoutMs:50});
  const server=http.createServer((req,res)=>gateway.handle(req,res));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const base=`http://127.0.0.1:${server.address().port}/edge-control/v1/`,headers={'x-thirdhand-edge-token':token,'content-type':'application/json'};
  const snapshot=await fetch(base+'context',{headers}).then(r=>r.json());
  const context={deviceId,bootId:randomUUID(),executorEpoch:snapshot.executorEpoch,connectionId:randomUUID(),certificateId:randomUUID()};
  const post=(route,value)=>fetch(base+route,{method:'POST',headers,body:JSON.stringify(value)}).then(r=>r.json());
  await post('bind',context);
  const signer=createEnvelopeSigner({keyId:'stop-test',privateKey:keys.privateKey});
  return {gateway,controller,context,outcomes,stop:()=>post('envelope',signer.sign({schema:1,...context,purpose:'stop',
    commandId:randomUUID(),leaseId:null,leaseEpoch:0,sequence:0,opcode:'software_stop',parameters:{},issuedAt:Date.now(),expiresAt:Date.now()+950}))};
}

test('physical stop cannot be confirmed by a stopped:true SDK/controller flag without independent feedback',async t=>{
  const f=await fixture(t);const result=await f.stop();assert.equal(result.state,'unknown');
  assert.equal(result.code,'STOP_UNCONFIRMED');assert.equal(f.gateway.policy.previousStopEvidence(),null);
  assert.equal(f.controller.calls[0].cmd,'software_stop');
});

test('read-only SDK release failure does not become a successful stop receipt',async t=>{
  const f=await fixture(t,{readOnly:true,release:false});const result=await f.stop();
  assert.equal(result.state,'unknown');assert.equal(result.code,'STOP_UNCONFIRMED');
  assert.equal(f.outcomes[0].code,'SDK_RELEASE_UNCONFIRMED');
  assert.equal(f.controller.calls[0].cmd,'disconnect');
});

test('read-only successful SDK release remains explicitly separate from physical stop evidence',async t=>{
  const f=await fixture(t,{readOnly:true,release:true});const result=await f.stop();
  assert.equal(result.state,'stopped');assert.equal(result.code,'READ_ONLY_SDK_DISCONNECTED');
});

test('missing newer SDK-release evidence remains unknown in the modern read-only gateway',async t=>{
  const f=await fixture(t,{readOnly:true,release:undefined});
  f.controller.handleCommand=command=>{f.controller.calls.push(command);f.controller.emit('message',{type:'connection',connected:false});};
  const result=await f.stop();assert.equal(result.state,'unknown');assert.equal(result.code,'STOP_UNCONFIRMED');
  assert.equal(f.outcomes[0].code,'STOP_UNCONFIRMED');
});

test('another SDK release request cannot confirm the current stop or permit rebinding',async t=>{
  const f=await fixture(t,{readOnly:true,release:true,releaseRequestId:randomUUID()});
  const result=await f.stop();assert.equal(result.state,'unknown');
  assert.equal(result.code,'STOP_UNCONFIRMED');assert.equal(f.gateway.policy.canBind(),false);
});
