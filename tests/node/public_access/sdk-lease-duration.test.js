'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');

for(const [mode,scope,ttl] of [['observe','sdk',3000],['admin','control',1000]]){
  test(`${scope} signed and stored lifetime is ${ttl}ms; expired records cannot be renewed`,async t=>{
    const f=await controlFixture(t),p=await f.principal(f.first.userId,mode),browser=f.browser(p);
    const lease=await f.service.requestLease(p,{...browser,deviceId:f.deviceId});
    assert.equal(lease.scope,scope);
    assert.equal(lease.expiresAt.getTime()-f.clock.value,ttl);
    const grant=f.requests.find(x=>x.purpose==='lease_grant');
    assert.equal(grant.expiresAt-grant.issuedAt,ttl);
    f.clock.value+=mode==='observe'?1500:250;browser.refresh();await f.service.drain();
    const renewed=f.requests.filter(x=>x.purpose==='lease_renew').at(-1);
    assert.equal(renewed.expiresAt-renewed.issuedAt,ttl);
    const current=await f.repo.find(lease.id);assert.equal(current.expiresAt.getTime()-f.clock.value,ttl);
    f.clock.value+=ttl;
    await assert.rejects(f.repo.renew(p,lease.id),{code:'LEASE_CHANGED'});
  });
}
