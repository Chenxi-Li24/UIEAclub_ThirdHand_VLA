'use strict';
const {randomUUID,randomBytes}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createUsersRepository}=require('../../../platform/storage/src/users');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {createLeasesRepository}=require('../../../platform/storage/src/leases');
const {createBrowserControlRegistry}=require('../../../services/cloud-api/src/control/control-channel');
const {createControlService}=require('../../../services/cloud-api/src/control/leases');

async function controlFixture(t){
  let service;t.after(()=>service?.close());
  const f=await identityFixture(t),users=createUsersRepository(f.pool),a=await f.verified('holder'),b=await f.verified('takeover');
  await users.bootstrapAdmin({verifiedUserId:a.userId});await users.requestAdmin({userId:b.userId,reason:'test only'});await users.setRole({actorId:a.userId,userId:b.userId,role:'admin',expectedVersion:1,reason:'test only'});
  const sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock});
  const cookies=new Map();
  async function principal(id){const s=await sessions.issue({userId:id,mode:'admin',mfaVerifiedAt:f.clock.now()});const p=await sessions.resolveSession({headers:{cookie:s.cookie.split(';')[0]}});cookies.set(p.sessionId,s.cookie.split(';')[0]);return p;}
  const first=await principal(a.userId),second=await principal(b.userId);
  const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial,enabled) VALUES('FakeRobot','test-fake',true) RETURNING id")).rows[0].id;
  const context={deviceId,bootId:randomUUID(),executorEpoch:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),controlAccepted:true};
  await f.pool.query(`INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,$2,'fake',$3,'test-only',$4,$5)`,[context.certificateId,deviceId,'b'.repeat(64),new Date(f.clock.value-60000),new Date(f.clock.value+86400000)]);
  await f.pool.query("UPDATE ops.device_credentials SET control_enabled=true,control_mode='full' WHERE id=$1",[context.certificateId]);
  await f.pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'fake-test')",[context.bootId,deviceId]);
  await f.pool.query("INSERT INTO ops.execution_instances(executor_epoch,device_id,boot_id,worker_instance_id,binding_confirmation) VALUES($1,$2,$3,'fake-only',$4)",[context.executorEpoch,deviceId,context.bootId,{fake:true}]);
  const clock={now:()=>f.clock.now(),monotonic:()=>f.clock.value};
  const channels=createBrowserControlRegistry({clock});
  const requests=[];let stopState='stopped',afterStop=null;
  const devices={get:()=>context,async request(id,envelope){const value=JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));requests.push(value);if(value.purpose==='stop'){if(afterStop)await afterStop();return {commandId:value.commandId,state:stopState};}if(value.purpose.startsWith('lease_'))return {state:'active',leaseId:value.leaseId,leaseEpoch:value.leaseEpoch};return {commandId:value.commandId,state:'completed'};}};
  const sign={sign:value=>({keyId:'test',payloadBase64url:Buffer.from(JSON.stringify(value)).toString('base64url'),signatureBase64url:'test-only'})};
  const repo=createLeasesRepository(f.pool,{clock:f.clock});
  service=createControlService({pool:f.pool,repository:repo,sessions,channels,devices,signer:sign,clock,readiness:async()=>true});
  function browser(p){const clientInstanceId=randomUUID(),messages=[];const connection=channels.open(p,{clientInstanceId,send:v=>messages.push(v)});function refresh(){const challenge=channels.challenge(connection.connectionId);channels.respond(p,{connectionId:connection.connectionId,sequence:challenge.sequence,nonce:challenge.nonce});}refresh();return {clientInstanceId,connectionId:connection.connectionId,refresh,messages};}
  return {...f,first,second,deviceId,context,repo,service,sessions,channels,devices,requests,browser,principal,cookieFor:p=>cookies.get(p.sessionId),setStopState(value){stopState=value;},onStop(callback){afterStop=callback;}};
}
module.exports={controlFixture};
