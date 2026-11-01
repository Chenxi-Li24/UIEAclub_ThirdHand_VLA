'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {controlFixture}=require('./control-fixture');

for(const phase of ['grant','renewal'])for(const known of [true,false])test(`${phase} rejection logs only allowlisted device outcome and still revokes when logger throws (${known?'known':'unknown'})`,async t=>{
  const records=[],f=await controlFixture(t,{onDiagnostic:record=>{records.push(record);throw Error('sink unavailable');}}),browser=f.browser(f.first);
  if(phase==='renewal')await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  const original=f.devices.request;
  f.devices.request=async(id,envelope)=>{
    const payload=JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));
    if(payload.purpose===`lease_${phase==='grant'?'grant':'renew'}`)return {
      state:known?'rejected':'private-state',code:known?'DEVICE_REQUEST_REJECTED':'PRIVATE_TOKEN',
      leaseId:'private-id',leaseEpoch:'private-epoch',scope:'private-scope',credentials:'PRIVATE_TOKEN',
    };
    return original(id,envelope);
  };
  if(phase==='grant')await assert.rejects(f.service.requestLease(f.first,{deviceId:f.deviceId,...browser}),{code:'LEASE_UNCONFIRMED'});
  else{browser.refresh();await f.service.drain();}
  assert.deepEqual(records[0],{component:'sdk_lease_confirmation',phase,
    deviceState:known?'rejected':'UNRECOGNIZED',deviceCode:known?'DEVICE_REQUEST_REJECTED':'UNRECOGNIZED',
    leaseIdMatches:false,leaseEpochMatches:false,scopeMatches:false});
  assert.equal(Object.isFrozen(records[0]),true);
  assert.equal(JSON.stringify(records).includes('private'),false);
  assert.equal(JSON.stringify(records).includes('PRIVATE_TOKEN'),false);
  assert.equal(await f.repo.current(f.deviceId),null);
  assert.equal(f.requests.at(-1).purpose,'stop');
});

test('an active acknowledgement with a mismatched epoch is diagnosed without logging binding identifiers',async t=>{
  const records=[],f=await controlFixture(t,{onDiagnostic:record=>records.push(record)}),browser=f.browser(f.first);
  await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser});
  assert.deepEqual(records,[]);
  const original=f.devices.request;
  f.devices.request=async(...args)=>{
    const result=await original(...args);
    return result.state==='active'?{...result,leaseEpoch:result.leaseEpoch+1}:result;
  };
  browser.refresh();await f.service.drain();
  assert.deepEqual(records[0],{component:'sdk_lease_confirmation',phase:'renewal',deviceState:'active',
    deviceCode:'UNRECOGNIZED',leaseIdMatches:true,leaseEpochMatches:false,scopeMatches:true});
  assert.equal(await f.repo.current(f.deviceId),null);
  assert.equal(f.requests.at(-1).purpose,'stop');
});
