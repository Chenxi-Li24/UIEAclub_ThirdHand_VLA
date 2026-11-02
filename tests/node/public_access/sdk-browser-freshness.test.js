'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createBrowserControlRegistry}=require('../../../services/cloud-api/src/control/control-channel');
const {controlFixture}=require('./control-fixture');

function registry(mode='observe'){
  const principal={userId:randomUUID(),sessionId:randomUUID(),role:'admin',mode,roleVersion:1,mfaVerifiedAt:new Date()};
  const clock={value:1000,monotonic(){return this.value;}};
  const channels=createBrowserControlRegistry({clock}),clientInstanceId=randomUUID();
  const bound=channels.open(principal,{clientInstanceId,send(){}}),binding={connectionId:bound.connectionId,clientInstanceId};
  const challenge=()=>channels.challenge(bound.connectionId);
  const respond=value=>channels.respond(principal,{connectionId:bound.connectionId,sequence:value.sequence,nonce:value.nonce});
  return {principal,clock,channels,binding,bound,challenge,respond};
}
test('observer challenge tolerates jitter but expires from issue time, without replay or mode escalation',()=>{
  const f=registry(),first=f.challenge();assert.equal(f.bound.freshnessMs,3000);
  for(let i=0;i<5;i++){f.clock.value+=250;f.challenge();}
  f.respond(first);assert.equal(f.channels.requireFresh(f.principal,f.binding),true);
  assert.throws(()=>f.respond(first),{code:'STALE_CHALLENGE'});
  assert.throws(()=>f.channels.requireFresh({...f.principal,mode:'admin'},f.binding),{code:'FORBIDDEN'});
  f.clock.value=3999;assert.equal(f.channels.requireFresh(f.principal,f.binding),true);
  f.clock.value=4000;assert.throws(()=>f.channels.requireFresh(f.principal,f.binding),{code:'BROWSER_STALE'});
  const late=registry(),response=late.challenge();late.clock.value+=3000;
  assert.throws(()=>late.respond(response),{code:'STALE_CHALLENGE'});
});
test('motion mode retains the 500ms boundary and at most two outstanding challenges',()=>{
  const f=registry('admin'),first=f.challenge();assert.equal(f.bound.freshnessMs,500);
  f.clock.value+=500;assert.throws(()=>f.respond(first),{code:'STALE_CHALLENGE'});
  const oldest=f.challenge();f.challenge();f.challenge();
  assert.throws(()=>f.respond(oldest),{code:'STALE_CHALLENGE'});
});
test('SDK timer bridges a missing browser response, keeps 1s signed leases, then revokes at 3s',async t=>{
  const f=await controlFixture(t),p=await f.principal(f.first.userId,'observe'),browser=f.browser(p);
  const lease=await f.service.requestLease(p,{deviceId:f.deviceId,...browser});assert.equal(lease.scope,'sdk');
  const tick=async()=>{f.clock.value+=300;await new Promise(resolve=>setTimeout(resolve,110));await f.service.drain();};
  for(let i=0;i<9;i++)await tick();
  const renewals=f.requests.filter(value=>value.purpose==='lease_renew');assert.ok(renewals.length>=9);
  assert.ok(renewals.every(value=>value.scope==='sdk'&&value.expiresAt-value.issuedAt===1000));
  assert.equal(f.requests.some(value=>value.purpose==='command'||value.purpose==='stop'),false);
  await tick();assert.equal(f.requests.at(-1).purpose,'stop');
  const count=f.requests.length;await tick();assert.equal(f.requests.length,count);
  assert.throws(()=>browser.refresh(),{code:'FORBIDDEN'});
  await assert.rejects(f.service.renewFromBrowser(p,{deviceId:f.deviceId,...browser}));
});
test('SDK timer cannot continue after session revocation and motion leases do not get timer renewal',async t=>{
  const f=await controlFixture(t),p=await f.principal(f.first.userId,'observe'),browser=f.browser(p);
  await f.service.requestLease(p,{deviceId:f.deviceId,...browser});
  f.sessions.events.emit('revoked',{sessionId:p.sessionId});await f.service.drain();
  f.clock.value+=300;await new Promise(resolve=>setTimeout(resolve,110));await f.service.drain();
  assert.equal(f.requests.filter(value=>value.purpose==='lease_renew').length,0);
  const admin=f.browser(f.first);await f.service.requestLease(f.first,{deviceId:f.deviceId,...admin});
  f.clock.value+=300;await new Promise(resolve=>setTimeout(resolve,110));await f.service.drain();
  assert.equal(f.requests.filter(value=>value.purpose==='lease_renew').length,0);
  f.clock.value+=200;await new Promise(resolve=>setTimeout(resolve,110));await f.service.drain();
  assert.equal(f.requests.at(-1).purpose,'stop');
});
