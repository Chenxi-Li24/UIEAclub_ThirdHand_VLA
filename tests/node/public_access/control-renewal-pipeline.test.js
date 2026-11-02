'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
const tick=()=>new Promise(resolve=>setTimeout(resolve,20));
async function until(predicate){for(let i=0;i<50;i++){if(predicate())return;await tick();}assert.fail('expected dispatch did not occur');}

test('a fresh browser event can send a later signed renewal while an earlier acknowledgement is delayed',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const held=deferred(),original=f.devices.request;let calls=0;
  f.devices.request=async(...args)=>{const result=await original(...args);if(result.state==='active'&&++calls===1)await held.promise;return result;};
  try{
    browser.refresh();await until(()=>calls===1);
    f.clock.value+=250;browser.refresh();await until(()=>calls===2);
    const renewals=f.requests.filter(x=>x.purpose==='lease_renew');
    assert.deepEqual(renewals.map(x=>x.sequence),[1,2]);
    assert.equal(renewals[1].issuedAt-renewals[0].issuedAt,250);
    assert.ok(renewals.every(x=>x.expiresAt-x.issuedAt===1000));
  }finally{held.resolve();await f.service.drain();}
  assert.equal((await f.repo.current(f.deviceId)).state,'active');
});

for(const ending of ['resume','stale','revoked','rejected'])test(`renewal pipeline bounds outstanding ACKs and one queued event; ${ending} never bypasses revocation`,async t=>{
  const records=[],f=await controlFixture(t,{onDiagnostic:value=>records.push(value)}),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const held=[],original=f.devices.request;
  f.devices.request=async(...args)=>{
    const result=await original(...args);
    if(result.state!=='active')return result;
    const gate=deferred();held.push(gate);const override=await gate.promise;
    return override||result;
  };
  try{
    for(let i=1;i<=4;i++){f.clock.value+=100;browser.refresh();await until(()=>held.length===i);}
    for(let i=0;i<6;i++){f.clock.value+=10;browser.refresh();}
    await tick();assert.equal(held.length,4);
    if(ending==='stale')f.clock.value+=501;
    if(ending==='revoked')f.channels.close(browser.connectionId);
    held[0].resolve(ending==='rejected'?{state:'rejected',code:'LEASE_EXPIRED'}:undefined);
    if(ending==='resume'){
      await until(()=>held.length===5);await tick();assert.equal(held.length,5);
      // Resolve in reverse order to exercise out-of-order confirmations.
      for(const item of held.slice(1).reverse())item.resolve();
      await f.service.drain();await tick();assert.equal(held.length,5);
      assert.equal((await f.repo.current(f.deviceId)).state,'active');
    }else{
      await until(()=>f.requests.some(x=>x.purpose==='stop'));
      for(const item of held)item.resolve();await f.service.drain();
      assert.equal(held.length,4);assert.equal(await f.repo.current(f.deviceId),null);
      assert.equal(f.requests.at(-1).purpose,'stop');
    }
    assert.ok(f.requests.filter(x=>x.purpose==='lease_renew').every(x=>x.expiresAt-x.issuedAt===1000));
    assert.equal(f.requests.some(x=>x.purpose==='command'),false);
  }finally{for(const item of held)item.resolve();await f.service.drain();}
});

test('a slow database keeps dispatch ordered and merges pending browser events without parallel writes',async t=>{
  const f=await controlFixture(t),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const gate=deferred(),original=f.repo.renew;let entered=0,active=0,maximum=0;
  f.repo.renew=async(...args)=>{
    active++;maximum=Math.max(maximum,active);
    try{if(++entered===1)await gate.promise;return await original(...args);}finally{active--;}
  };
  try{
    browser.refresh();await until(()=>entered===1);
    for(let i=0;i<5;i++){f.clock.value+=20;browser.refresh();}
    await tick();assert.equal(entered,1);assert.equal(f.requests.filter(x=>x.purpose==='lease_renew').length,0);
  }finally{gate.resolve();await f.service.drain();}
  assert.equal(maximum,1);assert.equal(entered,2);
  assert.deepEqual(f.requests.filter(x=>x.purpose==='lease_renew').map(x=>x.sequence),[1,2]);
});
