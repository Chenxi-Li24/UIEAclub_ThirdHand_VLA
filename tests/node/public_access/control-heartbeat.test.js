'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');

test('only fresh browser challenge responses renew; duplicate or old connection cannot revive a lease',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const challenge=f.channels.challenge(browser.connectionId);
  f.channels.respond(f.first,{connectionId:browser.connectionId,sequence:challenge.sequence,nonce:challenge.nonce});
  await f.service.drain();assert.equal(f.requests.at(-1).purpose,'lease_renew');
  assert.throws(()=>f.channels.respond(f.first,{connectionId:browser.connectionId,sequence:challenge.sequence,nonce:challenge.nonce}),{code:'STALE_CHALLENGE'});
  f.clock.value+=501;
  await f.service.renewFromBrowser(f.first,{deviceId:f.deviceId,...browser}).then(()=>assert.fail('stale renewal accepted'),error=>assert.equal(error.code,'BROWSER_STALE'));
  const count=f.requests.filter(x=>x.purpose==='lease_renew').length;
  f.channels.close(browser.connectionId);await f.service.drain();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,count);
  assert.equal(f.requests.at(-1).purpose,'stop');
});

test('overlapping browser responses coalesce renewal rather than deliver out-of-order lease sequences',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const original=f.devices.request;f.devices.request=async(...args)=>{await new Promise(resolve=>setTimeout(resolve,20));return original(...args);};
  await Promise.all([f.service.renewFromBrowser(f.first,{deviceId:f.deviceId,...browser}),f.service.renewFromBrowser(f.first,{deviceId:f.deviceId,...browser})]);
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,1);
});
