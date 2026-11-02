'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createRobotControlPolicy}=require('../../../services/robot/src/control-policy');

function fixture(){
  const clock={wall:10000,mono:5000,now(){return this.wall;},monotonic(){return this.mono;}};
  const state={executorEpoch:randomUUID(),hardwareFingerprint:'test-worker-can0',freshAt:10000};
  const calls=[];
  const policy=createRobotControlPolicy({deviceId:randomUUID(),getExecutionState:()=>state,clock,async submit(command){calls.push(command);return {state:command.opcode==='software_stop'?'stopped':'completed',commandId:command.commandId};}});
  const context={deviceId:policy.deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch:state.executorEpoch};
  policy.bind(context);
  const lease={...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:10000,expiresAt:11000};
  const command=overrides=>({...context,purpose:'command',commandId:randomUUID(),leaseId:lease.leaseId,leaseEpoch:1,sequence:1,issuedAt:10000,expiresAt:10500,opcode:'connect',parameters:{},...overrides});
  return {clock,state,calls,policy,context,lease,command};
}

test('SDK three-second lease tolerates a one-second gap, denies motion and cannot revive after expiry',async()=>{
  const f=fixture();
  try{
    assert.equal((await f.policy.handle({...f.lease,scope:'sdk',expiresAt:13000})).state,'active');
    f.clock.wall+=1500;f.clock.mono+=1500;
    const renew={...f.lease,purpose:'lease_renew',scope:'sdk',sequence:1,issuedAt:11500,expiresAt:14500};
    assert.equal((await f.policy.handle(renew)).state,'active');
    assert.equal((await f.policy.handle(f.command({issuedAt:11500,expiresAt:12000,opcode:'gripper',parameters:{position:1}}))).code,'SDK_CONNECTION_ONLY');
    assert.equal((await f.policy.handle({...renew,scope:'control',expiresAt:12500,sequence:2})).code,'LEASE_SCOPE_CHANGED');
    f.clock.wall=14500;f.clock.mono=9500;
    assert.equal((await f.policy.handle({...renew,sequence:3,issuedAt:14500,expiresAt:17500})).code,'STALE_LEASE');
    assert.equal(f.policy.currentLease(),null);
    assert.deepEqual(f.calls.map(x=>x.opcode),['software_stop']);
  }finally{await f.policy.close();}
  const strict=fixture();
  try{assert.equal((await strict.policy.handle({...strict.lease,scope:'control',expiresAt:13000})).code,'INVALID_LEASE');}
  finally{await strict.policy.close();}
});

test('SDK-scoped signed leases reject all motion and cannot be upgraded by renewal or command fields',async()=>{
  const f=fixture();
  assert.equal((await f.policy.handle({...f.lease,scope:'sdk'})).scope,'sdk');
  assert.equal((await f.policy.handle(f.command())).state,'completed');
  for(const [opcode,parameters] of [['move_joint',{joints:[0,0,0,0,0,0]}],['gripper',{position:1}],['preset',{name:'home'}]]){
    assert.equal((await f.policy.handle(f.command({sequence:2,scope:'control',opcode,parameters}))).code,'SDK_CONNECTION_ONLY');
  }
  assert.equal((await f.policy.handle({...f.lease,purpose:'lease_renew',sequence:1,scope:'control'})).code,'LEASE_SCOPE_CHANGED');
  assert.equal((await f.policy.handle({...f.lease,purpose:'lease_renew',sequence:1,scope:'sdk'})).scope,'sdk');
  assert.deepEqual(f.calls.map(x=>x.opcode),['connect']);
  assert.equal((await f.policy.handle(f.command({sequence:3,opcode:'disconnect'}))).state,'stopped');
});

test('bind and state subscription do not connect; only current bound lease can submit',async()=>{
  const f=fixture();assert.equal(f.calls.length,0);
  assert.equal((await f.policy.handle(f.command())).state,'rejected');
  assert.equal((await f.policy.handle(f.lease)).state,'active');
  assert.equal((await f.policy.handle(f.command())).state,'completed');assert.equal(f.calls.length,1);
  assert.equal((await f.policy.handle(f.command())).state,'rejected');assert.equal(f.calls.length,1);
});

test('renewal after local expiry reports stale lease without reviving SDK authority',async()=>{
  const f=fixture();
  try{
    await f.policy.handle({...f.lease,scope:'sdk'});
    f.clock.wall+=1001;f.clock.mono+=1001;
    const result=await f.policy.handle({...f.lease,purpose:'lease_renew',scope:'sdk',sequence:1,
      issuedAt:f.clock.wall,expiresAt:f.clock.wall+1000});
    assert.equal(result.code,'STALE_LEASE');
    assert.equal(f.policy.currentLease(),null);
    assert.deepEqual(f.calls.map(value=>value.opcode),['software_stop']);
    assert.equal(f.calls[0].reason,'lease_expired');
    assert.equal((await f.policy.handle(f.command({issuedAt:f.clock.wall,expiresAt:f.clock.wall+500}))).code,'LEASE_REQUIRED');
  }finally{await f.policy.close();}
});

test('independent monotonic watchdog revokes before requesting priority stop, despite wall clock rollback',async()=>{
  const f=fixture();await f.policy.handle(f.lease);f.clock.wall-=10000;f.clock.mono+=1001;
  await f.policy.expire();assert.equal(f.policy.currentLease(),null);assert.equal(f.calls.at(-1).opcode,'software_stop');
  assert.equal((await f.policy.handle(f.command({sequence:2}))).state,'rejected');
});

test('worker/CAN change and stale 500ms state deny motion; stop is independent of holder and freshness',async()=>{
  const f=fixture();await f.policy.handle(f.lease);
  f.state.freshAt=9499;
  assert.equal((await f.policy.handle(f.command({opcode:'move_joint',parameters:{joints:[0,0,0,0,0,0]}}))).code,'ROBOT_STATE_STALE');
  const stopped=await f.policy.handle(f.command({purpose:'stop',opcode:'software_stop',leaseId:null,leaseEpoch:0,sequence:0}));
  assert.equal(stopped.state,'stopped');assert.equal(f.policy.currentLease(),null);
  const again=fixture();await again.policy.handle(again.lease);again.state.hardwareFingerprint='other-can-config';
  await again.policy.expire();assert.equal(again.policy.currentLease(),null);
  assert.equal((await again.policy.handle(again.command())).state,'rejected');
});

test('an old executor cannot regain a lease or issue a stop in a replacement executor',async()=>{
  const f=fixture();await f.policy.handle(f.lease);
  const old=f.context;f.state.executorEpoch=randomUUID();
  await f.policy.expire();
  assert.equal((await f.policy.handle({...f.lease,leaseEpoch:2})).state,'rejected');
  assert.equal((await f.policy.handle(f.command({purpose:'stop',opcode:'software_stop',executorEpoch:old.executorEpoch}))).state,'rejected');
});

test('an unknown stop blocks every new grant until a confirmed stop',async()=>{
  const clock={now:()=>10000,monotonic:()=>1000},executorEpoch=randomUUID(),deviceId=randomUUID();
  let confirmed=false;
  const policy=createRobotControlPolicy({deviceId,clock,getExecutionState:()=>({executorEpoch,hardwareFingerprint:'same',freshAt:10000}),async submit(value){return {commandId:value.commandId,state:confirmed?'stopped':'unknown'};}});
  const context={deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch};policy.bind(context);
  assert.equal((await policy.revoke()).state,'unknown');
  const grant={...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:10000,expiresAt:11000};
  assert.equal((await policy.handle(grant)).code,'STOP_UNCONFIRMED');
  confirmed=true;await policy.revoke();assert.equal((await policy.handle(grant)).state,'active');
});

test('overlapping priority stops share one physical request while each receipt keeps its command ID',async()=>{
  const clock={now:()=>10000,monotonic:()=>1000},executorEpoch=randomUUID(),deviceId=randomUUID();
  let finish;const calls=[],receipts=[];
  const policy=createRobotControlPolicy({deviceId,clock,getExecutionState:()=>({executorEpoch,hardwareFingerprint:'stable',freshAt:10000}),submit:value=>{calls.push(value);return new Promise(resolve=>{finish=resolve;});},onStopReceipt:value=>receipts.push(value)});
  const context={deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch};policy.bind(context);
  await policy.handle({...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:10000,expiresAt:11000});
  const request=()=>({...context,purpose:'stop',opcode:'software_stop',parameters:{},leaseId:null,leaseEpoch:0,sequence:0,commandId:randomUUID(),issuedAt:10000,expiresAt:11000});
  const a=request(),b=request(),first=policy.handle(a),second=policy.handle(b);
  await new Promise(setImmediate);assert.equal(calls.length,1);
  finish({state:'stopped',commandId:calls[0].commandId});
  assert.equal((await first).commandId,a.commandId);assert.equal((await second).commandId,b.commandId);assert.equal(receipts.length,2);
});

test('confirmed prior stop evidence is available for a new connection only with the same executor and hardware',async()=>{
  const f=fixture(),old={...f.context};await f.policy.handle(f.lease);await f.policy.revoke('browser_disconnected');
  const evidence=f.policy.previousStopEvidence();assert.equal(evidence.state,'stopped');assert.equal(evidence.leaseId,f.lease.leaseId);assert.equal(evidence.connectionId,old.connectionId);
  f.policy.bind({...old,bootId:randomUUID(),connectionId:randomUUID()});assert.deepEqual(f.policy.previousStopEvidence(),evidence);
  f.state.hardwareFingerprint='different';assert.equal(f.policy.previousStopEvidence(),null);
});
