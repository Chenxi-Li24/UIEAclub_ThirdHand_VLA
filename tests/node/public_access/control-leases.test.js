'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {controlFixture}=require('./control-fixture');

test('two administrators or tabs race for one lease, and a new login does not displace it',async t=>{
  const f=await controlFixture(t),a=f.browser(f.first),b=f.browser(f.second);
  const outcomes=await Promise.allSettled([f.service.requestLease(f.first,{deviceId:f.deviceId,...a}),f.service.requestLease(f.second,{deviceId:f.deviceId,...b})]);
  assert.equal(outcomes.filter(x=>x.status==='fulfilled').length,1);assert.equal(outcomes.find(x=>x.status==='rejected').reason.code,'LEASE_BUSY');
  assert.equal(f.requests.filter(x=>x.purpose==='lease_grant').length,1);
  await f.principal(f.second.userId);assert.equal(f.requests.filter(x=>x.purpose==='stop').length,0);
  const holder=outcomes[0].status==='fulfilled'?f.first:f.second,own=outcomes[0].status==='fulfilled'?a:b;
  const lease=outcomes.find(x=>x.status==='fulfilled').value;
  const otherTab=f.browser(holder);
  await assert.rejects(f.service.dispatchRealCommand(holder,{deviceId:f.deviceId,leaseId:lease.id,...otherTab,commandId:randomUUID(),opcode:'connect',parameters:{}}),{code:'FORBIDDEN'});
  const commandId=randomUUID(),request={deviceId:f.deviceId,leaseId:lease.id,...own,commandId,opcode:'connect',parameters:{}};
  assert.equal((await f.service.dispatchRealCommand(holder,request)).state,'completed');
  assert.equal((await f.service.dispatchRealCommand(holder,request)).state,'completed');
  assert.equal(f.requests.filter(x=>x.purpose==='command').length,1);
});

test('session revocation stops its lease and observer mode cannot request control',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  await f.sessions.revokeSession({sessionId:f.first.sessionId,reason:'logout'});
  await f.service.drain();
  assert.equal(f.requests.at(-1).purpose,'stop');
  await assert.rejects(f.service.requestLease({...f.second,mode:'observe'},{deviceId:f.deviceId,...f.browser(f.second)}),{code:'FORBIDDEN'});
});
