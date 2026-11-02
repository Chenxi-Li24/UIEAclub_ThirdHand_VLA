'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {createLeaseTiming}=require('../../../services/device-relay/src/lease-timing');
const {controlFixture}=require('./control-fixture');
const envelope={payloadBase64url:Buffer.from(JSON.stringify({issuedAt:1000,secret:'must-not-log'})).toString('base64url'),signatureBase64url:'private-signature'};

test('timing has bounded duration, event count and allowlisted fields; disabled means no record',()=>{
  let now=0;const records=[],timing=createLeaseTiming({enabled:true,mono:()=>now,wall:()=>1000,sink:r=>records.push(r),limit:2,windowMs:100});
  const trace=timing.begin(envelope);trace.mark('queued');now=12;trace.mark('principal');trace.mark('private-token');trace.finish('cloud','active');trace.finish('cloud','active');
  assert.equal(records.length,1);assert.equal(records[0].trace,createHash('sha256').update(envelope.payloadBase64url).digest('hex'));
  assert.deepEqual(records[0].marks,{queued:0,principal:12});assert.ok(!JSON.stringify(records).includes('private'));assert.ok(!JSON.stringify(records).includes('must-not-log'));
  timing.begin().finish('relay','failed');assert.equal(timing.begin(),null);
  const expiry=createLeaseTiming({enabled:true,mono:()=>now,windowMs:5,sink:r=>records.push(r)});const pending=expiry.begin();now+=6;pending.finish('cloud','active');assert.equal(expiry.begin(),null);assert.equal(records.length,2);
  assert.equal(createLeaseTiming({enabled:false}).begin(envelope),null);
  assert.doesNotThrow(()=>createLeaseTiming({enabled:true,sink:()=>{throw Error('sink failed');}}).begin(envelope).finish('cloud','failed'));
});

test('cloud records raw ACK before waiting for revocation and never changes lease validity',async t=>{
  let mono=0;const records=[],timing=createLeaseTiming({enabled:true,mono:()=>mono,sink:r=>records.push(r)});
  const f=await controlFixture(t,{timing});
  const session=await f.sessions.issue({userId:f.first.userId,mode:'observe'});
  const observer=await f.sessions.resolveSession({headers:{cookie:session.cookie.split(';')[0]}}),browser=f.browser(observer);
  await f.service.requestLease(observer,{deviceId:f.deviceId,...browser});
  const original=f.repo.renew;f.repo.renew=async(...args)=>{mono+=17;return original(...args);};
  let release,ack;const held=new Promise(resolve=>{release=resolve;});
  f.onStop(async()=>{await held;mono+=500;});
  f.devices.dispatch=async()=>{mono+=11;return {confirmation:new Promise(resolve=>{ack=resolve;})};};
  browser.refresh();
  try{
    for(let i=0;i<100&&!ack;i++)await new Promise(resolve=>setTimeout(resolve,5));
    assert.ok(ack);mono+=90;ack({state:'rejected',code:'LEASE_EXPIRED'});
    for(let i=0;i<100&&!records.length;i++)await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(records.length,1);assert.equal(records[0].marks.repository,17);assert.equal(records[0].marks.dispatched,28);assert.equal(records[0].marks.ack,118);
    assert.equal(records[0].outcome,'rejected');assert.match(records[0].trace,/^[a-f0-9]{64}$/);
  }finally{release();await f.service.drain();}
  assert.equal(records[0].marks.ack,118,'stop completion must not contaminate ACK timing');
  assert.equal(await f.repo.current(f.deviceId),null);assert.equal(f.requests.some(v=>v.purpose==='command'),false);
  assert.ok(f.requests.every(v=>v.expiresAt-v.issuedAt===1000));
});
