'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createRobotControlPolicy}=require('../../../services/robot/src/control-policy');

function fixture(t,{onLeaseChange=()=>true,onLeaseRevoke=()=>{}}={}){
  const clock={wall:10000,mono:5000,now(){return this.wall;},monotonic(){return this.mono;}};
  const state={executorEpoch:randomUUID(),hardwareFingerprint:'a'.repeat(64),freshAt:10000},calls=[];
  const policy=createRobotControlPolicy({deviceId:randomUUID(),getExecutionState:()=>state,clock,
    onLeaseChange,onLeaseRevoke,async submit(value){calls.push(value);return {state:value.opcode==='software_stop'?'stopped':'completed',commandId:value.commandId};}});
  const context={deviceId:policy.deviceId,bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID(),executorEpoch:state.executorEpoch};
  policy.bind(context);
  const grant={...context,purpose:'lease_grant',leaseId:randomUUID(),leaseEpoch:1,sequence:0,issuedAt:10000,expiresAt:10950};
  const command={...context,purpose:'command',commandId:randomUUID(),leaseId:grant.leaseId,leaseEpoch:1,sequence:1,issuedAt:10000,expiresAt:10900,opcode:'connect',parameters:{}};
  t.after(async()=>{if(policy.currentLease())await policy.revoke('test_cleanup');});
  return {clock,state,calls,policy,context,grant,command};
}

test('accepted grants and renewals propagate the original immutable lease to the worker guard',async t=>{
  const updates=[],revocations=[],f=fixture(t,{onLeaseChange:(value,isGrant)=>{updates.push({value,isGrant});return true;},onLeaseRevoke:value=>revocations.push(value)});
  assert.equal((await f.policy.handle(f.grant)).state,'active');
  assert.equal(updates.length,1);assert.equal(updates[0].isGrant,true);assert.equal(Object.isFrozen(updates[0].value),true);
  assert.deepEqual(updates[0].value,{...f.context,hardwareFingerprint:f.state.hardwareFingerprint,
    leaseId:f.grant.leaseId,leaseEpoch:1,sequence:0,issuedAt:10000,expiresAt:10950});
  f.clock.wall+=100;f.clock.mono+=100;
  assert.equal((await f.policy.handle({...f.grant,purpose:'lease_renew',sequence:1,issuedAt:10100,expiresAt:11000})).state,'active');
  assert.equal(updates[1].isGrant,false);assert.equal(updates[1].value.expiresAt,11000);
  await f.policy.revoke('remote_link_lost');
  assert.equal(revocations.length,1);assert.equal(revocations[0].reason,'remote_link_lost');assert.equal(revocations[0].leaseId,f.grant.leaseId);
});

test('a worker guard refusal cancels authority before any connect command',async t=>{
  const f=fixture(t,{onLeaseChange:()=>false});
  assert.equal((await f.policy.handle(f.grant)).code,'LOCAL_LEASE_GUARD_REJECTED');
  assert.equal(f.policy.currentLease(),null);
  assert.equal((await f.policy.handle(f.command)).state,'rejected');
  assert.deepEqual(f.calls.map(x=>x.opcode),['software_stop']);
});

test('SDK commands stay closed while the local guard is pending and late completion cannot revive a lease',async t=>{
  let finish;const f=fixture(t,{onLeaseChange:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=f.policy.handle(f.grant);await new Promise(setImmediate);
  assert.equal(typeof finish,'function');
  assert.equal((await f.policy.handle(f.command)).code,'LEASE_NOT_READY');
  f.clock.wall+=1000;f.clock.mono+=1000;finish(true);
  assert.equal((await pending).code,'LEASE_EXPIRED');assert.equal(f.policy.currentLease(),null);
  assert.equal(f.calls.some(x=>x.opcode==='connect'),false);
});

test('the independent software timer revokes an expired lease without gateway polling',async t=>{
  const f=fixture(t);await f.policy.handle({...f.grant,expiresAt:10025});
  f.clock.mono+=26;
  await new Promise(resolve=>setTimeout(resolve,50));
  assert.equal(f.policy.currentLease(),null);assert.equal(f.calls.at(-1).opcode,'software_stop');
});

test('a pause after sampling UTC cannot extend the signed deadline when arming the local guard',async t=>{
  const f=fixture(t);let once=true;
  f.clock.now=function(){const value=this.wall;if(once){once=false;this.wall+=200;this.mono+=200;}return value;};
  const result=await f.policy.handle({...f.grant,expiresAt:10080});
  assert.equal(result.state,'rejected');assert.equal(f.policy.currentLease(),null);
  assert.equal(f.calls.some(x=>x.opcode==='connect'),false);
});

test('a renewal sampling pause cannot restore a lease cleared by synchronous expiry',async t=>{
  const f=fixture(t);await f.policy.handle(f.grant);
  f.clock.wall=10100;f.clock.mono=5100;let reads=0;
  f.clock.monotonic=function(){if(++reads===3)this.mono=6000;return this.mono;};
  const result=await f.policy.handle({...f.grant,purpose:'lease_renew',sequence:1,issuedAt:10100,expiresAt:11000});
  assert.equal(result.code,'LEASE_EXPIRED');assert.equal(f.policy.currentLease(),null);
  assert.equal(f.policy.canBind(),true);assert.equal(f.calls.filter(x=>x.opcode==='software_stop').length,1);
});

test('rebind and stop evidence remain unavailable until the prior worker hook settles',async t=>{
  let finish;const f=fixture(t,{onLeaseChange:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=f.policy.handle(f.grant);await new Promise(setImmediate);
  await f.policy.revoke('test_revoke');
  assert.equal(f.policy.canBind(),false);assert.equal(f.policy.previousStopEvidence(),null);
  assert.throws(()=>f.policy.bind({...f.context,connectionId:randomUUID()}));
  finish(true);assert.equal((await pending).code,'LEASE_EXPIRED');
  assert.equal(f.policy.canBind(),true);assert.equal(f.policy.previousStopEvidence().state,'stopped');
});

test('policy shutdown is terminal even when a worker hook completes afterwards',async t=>{
  let finish;const f=fixture(t,{onLeaseChange:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=f.policy.handle(f.grant);await new Promise(setImmediate);
  assert.equal(typeof f.policy.close,'function');await f.policy.close();finish(true);
  assert.equal((await pending).state,'rejected');assert.equal(f.policy.canBind(),false);
  assert.equal((await f.policy.handle(f.command)).code,'POLICY_CLOSED');
  assert.equal((await f.policy.handle({...f.grant,leaseEpoch:2})).code,'POLICY_CLOSED');
  assert.equal(f.calls.some(x=>x.opcode==='connect'),false);
});
