'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {randomUUID,randomBytes,generateKeyPairSync}=require('node:crypto');
const {createRemoteRobotGateway}=require('../../../services/robot/src/remote-gateway');
const {createRobotService}=require('../../../services/robot/src/server');

async function fixture(t,{readOnly=true,worker=true,required=true}={}){
  const controller=new EventEmitter();controller.config={simulate:false,remoteLeaseGuard:required};
  controller.bridge=new EventEmitter();controller.bridge.child={pid:42};controller.bridge.connected=true;
  const workerCalls=[],outcomes=[];
  if(worker){
    controller.bridge.armRemoteLease=value=>{workerCalls.push({kind:'arm',value});return true;};
    controller.bridge.renewRemoteLease=value=>{workerCalls.push({kind:'renew',value});return true;};
    controller.bridge.revokeRemoteLease=reason=>{workerCalls.push({kind:'revoke',reason});return true;};
  }
  controller.on('message',value=>{if(value.type==='remote_command_outcome')outcomes.push(value);});
  controller.handleCommand=command=>controller.emit('message',{type:'connection',connected:false,
    request_id:command.request_id,sdk_released:true,cleanup_state:'completed',reason:command.cmd==='disconnect'?'requested':'software_stop'});
  const deviceId=randomUUID(),token=randomBytes(32).toString('hex'),keys=generateKeyPairSync('ed25519');
  const gateway=createRemoteRobotGateway({controller,deviceId,token,readOnly,signingKeys:new Map([['test',keys.publicKey]])});
  const server=require('node:http').createServer((q,s)=>gateway.handle(q,s));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(async()=>{await gateway.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  const snapshot=await fetch(`http://127.0.0.1:${server.address().port}/edge-control/v1/context`,{headers:{'x-thirdhand-edge-token':token}}).then(r=>r.json());
  const context={deviceId,bootId:randomUUID(),executorEpoch:snapshot.executorEpoch,connectionId:randomUUID(),certificateId:randomUUID()};
  gateway.policy.bind(context);
  const stamp=()=>({issuedAt:Date.now(),expiresAt:Date.now()+950});
  const lease={...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,...stamp()};
  return {controller,gateway,workerCalls,outcomes,lease,stamp,snapshot,context,token,keys};
}

test('the gateway forwards grant, renewal and revocation to the paired SDK worker guard',async t=>{
  const f=await fixture(t);
  assert.equal((await f.gateway.policy.handle(f.lease)).state,'active');
  assert.equal(f.workerCalls[0].kind,'arm');assert.equal(f.workerCalls[0].value.expiresAt,f.lease.expiresAt);
  assert.equal((await f.gateway.policy.handle({...f.lease,purpose:'lease_renew',sequence:1,...f.stamp()})).state,'active');
  assert.equal(f.workerCalls[1].kind,'renew');
  await f.gateway.policy.revoke('remote_link_lost');
  assert.equal(f.workerCalls[2].kind,'revoke');assert.equal(f.workerCalls[2].reason,'remote_link_lost');
});

test('a required but missing worker guard cannot grant SDK authority',async t=>{
  const f=await fixture(t,{worker:false});
  assert.equal((await f.gateway.policy.handle(f.lease)).code,'LOCAL_LEASE_GUARD_REJECTED');
  assert.equal(f.gateway.policy.currentLease(),null);
});

test('physical mode cleanup is reported as SDK release with unknown physical stop',async t=>{
  const f=await fixture(t,{readOnly:false,required:false});
  assert.equal(f.snapshot.stopCapabilities?.controlledStop,false);
  const result=await f.gateway.policy.revoke('remote_link_lost');
  assert.equal(result.state,'unknown');assert.equal(f.gateway.policy.canBind(),false);
  assert.equal(f.outcomes.at(-1).code,'CONTROLLED_STOP_UNSUPPORTED');
  assert.equal(f.outcomes.at(-1).sdkReleased,true);
});

test('remote service mode always enables the internal SDK worker lease guard',async t=>{
  const keys=generateKeyPairSync('ed25519');
  const service=createRobotService({remote:{enabled:true,readOnly:true,deviceId:randomUUID()},
    edgeToken:randomBytes(32).toString('hex'),cloudSigningKeys:new Map([['test',keys.publicKey]]),robot:{simulate:true,remoteLeaseGuard:false},
    readyFile:require('node:path').join(require('node:os').tmpdir(),'thirdhand-unused-'+randomUUID())});
  t.after(()=>service.close());assert.equal(service.controller.config.remoteLeaseGuard,true);
});

test('closed gateways reject signed requests, including bodies received during shutdown',async t=>{
  const {Readable}=require('node:stream');
  const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');
  const f=await fixture(t);f.controller.config.simulate=true;
  const signed=createEnvelopeSigner({keyId:'test',privateKey:f.keys.privateKey}).sign({schema:1,...f.lease});
  function response(){return {writeHead(status){this.status=status;},end(body){this.body=JSON.parse(body);}};}
  const headers={'x-thirdhand-edge-token':f.token,'content-type':'application/json'};
  const pendingRequest=new Readable({read(){}});Object.assign(pendingRequest,{url:'/edge-control/v1/envelope',method:'POST',headers,socket:{remoteAddress:'127.0.0.1'}});
  const pendingResponse=response(),pending=f.gateway.handle(pendingRequest,pendingResponse);
  await f.gateway.close();pendingRequest.push(JSON.stringify(signed));pendingRequest.push(null);await pending;
  assert.equal(pendingResponse.status,503);assert.equal(pendingResponse.body.error,'GATEWAY_CLOSED');
  const later=Readable.from([JSON.stringify(signed)]);Object.assign(later,{url:'/edge-control/v1/envelope',method:'POST',headers,socket:{remoteAddress:'127.0.0.1'}});
  const laterResponse=response();await f.gateway.handle(later,laterResponse);
  assert.equal(laterResponse.status,503);assert.equal(f.workerCalls.length,0);
});
