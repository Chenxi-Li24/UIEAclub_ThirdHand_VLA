'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');

test('takeover warning requires one-time explicit confirmation and stopped ACK before new grant',async t=>{
  const f=await controlFixture(t),a=f.browser(f.first),b=f.browser(f.second);
  const old=await f.service.requestLease(f.first,{deviceId:f.deviceId,...a});
  const warning=await f.service.requestTakeover(f.second,{deviceId:f.deviceId,targetEpoch:old.leaseEpoch,...b});
  assert.equal(warning.requiresConfirmation,true);assert.equal(f.requests.filter(x=>x.purpose==='stop').length,0);
  const granted=await f.service.confirmTakeover(f.second,{requestId:warning.requestId,nonce:warning.nonce,...b});
  assert.equal(granted.leaseEpoch,old.leaseEpoch+1);
  assert.deepEqual(f.requests.map(x=>x.purpose),['lease_grant','stop','lease_grant']);
  await assert.rejects(f.service.confirmTakeover(f.second,{requestId:warning.requestId,nonce:warning.nonce,...b}));
  assert.equal((await f.pool.query('SELECT revoked_at FROM auth.sessions WHERE id=$1',[f.first.sessionId])).rows[0].revoked_at,null);
});

test('stale takeover warning cannot stop a new holder; failed new grant is never recorded as granted',async t=>{
  const f=await controlFixture(t),a=f.browser(f.first),b=f.browser(f.second),old=await f.service.requestLease(f.first,{deviceId:f.deviceId,...a});
  const warning=await f.service.requestTakeover(f.second,{deviceId:f.deviceId,targetEpoch:old.leaseEpoch,...b});
  await f.service.stop(f.first,{deviceId:f.deviceId,...a});
  const renewedBrowser=f.browser(f.first);
  const newLease=await f.service.requestLease(f.first,{deviceId:f.deviceId,...renewedBrowser});
  const stops=f.requests.filter(x=>x.purpose==='stop').length;
  await assert.rejects(f.service.confirmTakeover(f.second,{requestId:warning.requestId,nonce:warning.nonce,...b}),{code:'LEASE_CHANGED'});
  assert.equal(f.requests.filter(x=>x.purpose==='stop').length,stops);
  const current=await f.service.requestTakeover(f.second,{deviceId:f.deviceId,targetEpoch:newLease.leaseEpoch,...b});
  const original=f.devices.request;f.devices.request=async(id,envelope)=>{const payload=JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));if(payload.purpose==='lease_grant')return {state:'unknown'};return original(id,envelope);};
  await assert.rejects(f.service.confirmTakeover(f.second,{requestId:current.requestId,nonce:current.nonce,...b}),{code:'LEASE_UNCONFIRMED'});
  assert.equal((await f.pool.query('SELECT state FROM ops.control_takeovers WHERE id=$1',[current.requestId])).rows[0].state,'failed');
});

test('unconfirmed stop and applicant logout during stop never grant new authority',async t=>{
  const f=await controlFixture(t),a=f.browser(f.first),b=f.browser(f.second),old=await f.service.requestLease(f.first,{deviceId:f.deviceId,...a});
  const warning=await f.service.requestTakeover(f.second,{deviceId:f.deviceId,targetEpoch:old.leaseEpoch,...b});
  f.setStopState('unknown');
  await assert.rejects(f.service.confirmTakeover(f.second,{requestId:warning.requestId,nonce:warning.nonce,...b}),{code:'STOP_UNCONFIRMED'});
  assert.equal(f.requests.filter(x=>x.purpose==='lease_grant').length,1);
  const other=await controlFixture(t),c=other.browser(other.first),d=other.browser(other.second),lease=await other.service.requestLease(other.first,{deviceId:other.deviceId,...c});
  const take=await other.service.requestTakeover(other.second,{deviceId:other.deviceId,targetEpoch:lease.leaseEpoch,...d});
  other.onStop(()=>other.sessions.revokeSession({sessionId:other.second.sessionId,reason:'logout'}));
  await assert.rejects(other.service.confirmTakeover(other.second,{requestId:take.requestId,nonce:take.nonce,...d}));
  assert.equal(other.requests.filter(x=>x.purpose==='lease_grant').length,1);
});
