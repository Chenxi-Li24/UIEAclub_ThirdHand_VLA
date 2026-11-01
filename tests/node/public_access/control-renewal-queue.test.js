'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');

function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}

test('fresh responses received during a delayed device ACK trigger one immediate serialized renewal',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const entered=deferred(),ack=deferred(),original=f.devices.request;let blocked=false;
  f.devices.request=async(...args)=>{
    const result=await original(...args);
    if(result.state==='active'&&!blocked){blocked=true;entered.resolve();await ack.promise;}
    return result;
  };
  browser.refresh();await entered.promise;
  // One latest browser event is retained; no parallel requests or unbounded queue.
  f.clock.value+=250;browser.refresh();
  f.clock.value+=250;browser.refresh();
  f.clock.value+=250;browser.refresh();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,1);
  f.clock.value+=100;ack.resolve();await f.service.drain();
  const renewals=f.requests.filter(x=>x.purpose==='lease_renew');
  assert.equal(renewals.length,2);
  assert.deepEqual(renewals.map(x=>x.sequence),[1,2]);
  assert.ok(renewals.every(x=>x.expiresAt-x.issuedAt===1000));
  assert.equal((await f.repo.current(f.deviceId)).state,'active');
});

test('queued browser freshness cannot renew after its 500ms deadline',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const entered=deferred(),ack=deferred(),original=f.devices.request;let blocked=false;
  f.devices.request=async(...args)=>{const result=await original(...args);if(result.state==='active'&&!blocked){blocked=true;entered.resolve();await ack.promise;}return result;};
  browser.refresh();await entered.promise;
  f.clock.value+=100;browser.refresh();f.clock.value+=501;
  ack.resolve();await f.service.drain();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,1);
  assert.equal(f.requests.at(-1).purpose,'stop');
  assert.equal(await f.repo.current(f.deviceId),null);
});

test('revocation during a delayed ACK discards queued renewals',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const entered=deferred(),ack=deferred(),original=f.devices.request;let blocked=false;
  f.devices.request=async(...args)=>{const result=await original(...args);if(result.state==='active'&&!blocked){blocked=true;entered.resolve();await ack.promise;}return result;};
  browser.refresh();await entered.promise;browser.refresh();
  f.channels.close(browser.connectionId);ack.resolve();await f.service.drain();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,1);
  assert.equal(await f.repo.current(f.deviceId),null);
});

test('a slow repository cannot dispatch renewal after browser revocation',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const entered=deferred(),finish=deferred(),original=f.repo.renew;
  f.repo.renew=async(...args)=>{const result=await original(...args);entered.resolve();await finish.promise;return result;};
  browser.refresh();await entered.promise;
  f.channels.close(browser.connectionId);finish.resolve();await f.service.drain();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,0);
  assert.equal(await f.repo.current(f.deviceId),null);
});

test('queued fresh events cannot revive an already expired database lease',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const entered=deferred(),ack=deferred(),original=f.devices.request;let blocked=false;
  f.devices.request=async(...args)=>{const result=await original(...args);if(result.state==='active'&&!blocked){blocked=true;entered.resolve();await ack.promise;}return result;};
  browser.refresh();await entered.promise;
  f.clock.value+=1001;browser.refresh();ack.resolve();await f.service.drain();
  assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,1);
  assert.equal(await f.repo.current(f.deviceId),null);
});

for(const code of ['DEVICE_REPLY_UNKNOWN','private-error-token-must-not-be-logged'])test(`renewal diagnostics sanitize ${code==='DEVICE_REPLY_UNKNOWN'?'known failure':'unknown failure'} and cannot prevent revocation`,async t=>{
  const records=[],f=await controlFixture(t,{onDiagnostic:value=>{records.push(value);throw Error('diagnostic sink failure');}}),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const original=f.devices.request;
  f.devices.request=async(id,envelope)=>{
    const value=JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));
    if(value.purpose==='lease_renew')throw Error(code);
    return original(id,envelope);
  };
  browser.refresh();await f.service.drain();
  assert.deepEqual(records,[{component:'sdk_renewal',stage:'device_reply',code:code==='DEVICE_REPLY_UNKNOWN'?code:'RENEWAL_FAILED',elapsedMs:0}]);
  assert.equal(await f.repo.current(f.deviceId),null);
  assert.equal(f.requests.at(-1).purpose,'stop');
});
