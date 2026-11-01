'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {controlFixture}=require('./control-fixture');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
const {WebSocket}=require('ws');
const {once}=require('node:events');
async function observer(f){
  const user=await f.verified('sdk_observer');
  const session=await f.sessions.issue({userId:user.userId,mode:'observe'});
  return f.sessions.resolveSession({headers:{cookie:session.cookie.split(';')[0]}});
}
test('observer SDK grant is scoped in storage and signatures, permits lifecycle, rejects movement at service and repository',async t=>{
  const f=await controlFixture(t),p=await observer(f),browser=f.browser(p);
  const lease=await f.service.requestLease(p,{deviceId:f.deviceId,...browser,scope:'control'});
  assert.equal(lease.scope,'sdk');assert.equal(f.requests.at(-1).scope,'sdk');
  const input={deviceId:f.deviceId,...browser,leaseId:lease.id,commandId:randomUUID(),opcode:'connect',parameters:{}};
  assert.equal((await f.service.dispatchRealCommand(p,input)).state,'completed');
  browser.refresh();await f.service.drain();assert.equal(f.requests.findLast(x=>x.purpose==='lease_renew').scope,'sdk');
  const before=f.requests.length;
  for(const [opcode,parameters] of [['move_joint',{joints:[0,0,0,0,0,0]}],['gripper',{position:0}],['preset',{name:'home'}],['software_stop',{}]]){
    const value={...input,commandId:randomUUID(),opcode,parameters};
    await assert.rejects(f.service.dispatchRealCommand(p,value),{code:'FORBIDDEN'});
    await assert.rejects(f.repo.recordCommand(p,{...value,expiresAt:new Date(f.clock.value+1000)}),{code:'FORBIDDEN'});
  }
  assert.equal(f.requests.length,before);assert.equal((await f.pool.query('SELECT count(*) FROM ops.commands')).rows[0].count,'1');
  assert.equal((await f.service.dispatchRealCommand(p,{...input,commandId:randomUUID(),opcode:'disconnect'})).state,'completed');
});
test('observer cannot take over, stop or use another administrator lease; a forged principal fails database checks',async t=>{
  const f=await controlFixture(t),p=await observer(f),browser=f.browser(p),adminBrowser=f.browser(f.first);
  const lease=await f.service.requestLease(f.first,{deviceId:f.deviceId,...adminBrowser});assert.equal(lease.scope,'control');
  await assert.rejects(f.service.requestLease(p,{deviceId:f.deviceId,...browser}),{code:'LEASE_BUSY'});
  await assert.rejects(f.service.requestTakeover(p,{deviceId:f.deviceId,...browser,targetEpoch:lease.leaseEpoch}),{code:'FORBIDDEN'});
  await assert.rejects(f.service.stop(p,{deviceId:f.deviceId,...browser}),{code:'FORBIDDEN'});
  await assert.rejects(f.service.dispatchRealCommand(p,{deviceId:f.deviceId,...browser,leaseId:lease.id,commandId:randomUUID(),opcode:'disconnect',parameters:{}}),{code:'FORBIDDEN'});
  await assert.rejects(f.repo.validatePrincipal({...p,role:'admin',mode:'admin',mfaVerifiedAt:new Date()},'control'),{code:'FORBIDDEN'});
});
test('SDK grant requires device scope acknowledgement, and revoked observers cannot renew or reconnect',async t=>{
  const f=await controlFixture(t),p=await observer(f),browser=f.browser(p);
  const original=f.devices.request.bind(f.devices);
  f.devices.request=async(...args)=>{const result=await original(...args);delete result.scope;return result;};
  await assert.rejects(f.service.requestLease(p,{deviceId:f.deviceId,...browser}),{code:'LEASE_UNCONFIRMED'});
  assert.equal(f.requests.some(x=>x.purpose==='command'),false);
  f.devices.request=original;const nextBrowser=f.browser(p),lease=await f.service.requestLease(p,{deviceId:f.deviceId,...nextBrowser});
  await f.pool.query('UPDATE auth.sessions SET revoked_at=$2 WHERE id=$1',[p.sessionId,f.clock.now()]);
  await assert.rejects(f.repo.renew(p,lease.id),{code:'FORBIDDEN'});
  await assert.rejects(f.service.dispatchRealCommand(p,{deviceId:f.deviceId,...nextBrowser,leaseId:lease.id,commandId:randomUUID(),opcode:'connect',parameters:{}}),{code:'FORBIDDEN'});
});

test('observer HTTP and WebSocket flow binds a real session and refuses motion before dispatch',async t=>{
  const f=await controlFixture(t),user=await f.verified('sdk_http'),issued=await f.sessions.issue({userId:user.userId,mode:'observe'});
  const cookie=issued.cookie.split(';')[0],p=await f.sessions.resolveSession({headers:{cookie}}),origin='https://thirdhand.example.invalid';
  const server=createCloudApi({...f,publicOrigin:origin,controlService:f.service,controlChannels:f.channels});
  t.after(async()=>{await server.controlChannel.close();server.closeAllConnections();await new Promise(r=>server.close(r));});
  await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}`;
  const ws=new WebSocket(base.replace('http','ws')+'/stream/v1/control',{headers:{Origin:origin,Cookie:cookie}});t.after(()=>ws.terminate());
  const clientInstanceId=randomUUID();let connectionId;
  const fresh=new Promise(resolve=>ws.on('message',raw=>{
    const v=JSON.parse(raw);if(v.type==='bound')connectionId=v.connectionId;
    if(v.type==='challenge')ws.send(JSON.stringify({type:'response',connectionId:v.connectionId,sequence:v.sequence,nonce:v.nonce}));
    if(v.type==='fresh')resolve();
  }));
  await once(ws,'open');ws.send(JSON.stringify({type:'bind',clientInstanceId,csrfToken:p.csrfToken}));await fresh;
  const post=(route,body)=>fetch(base+route,{method:'POST',headers:{Cookie:cookie,Origin:origin,'x-csrf-token':p.csrfToken,'content-type':'application/json'},body:JSON.stringify(body)});
  const browser={deviceId:f.deviceId,clientInstanceId,connectionId};
  const grant=await post('/api/v1/control/lease',browser);assert.equal(grant.status,200);const lease=await grant.json();assert.equal(lease.scope,'sdk');
  const command={...browser,leaseId:lease.id,commandId:randomUUID(),opcode:'connect',parameters:{}};
  assert.equal((await post('/api/v1/control/command',command)).status,200);
  for(const opcode of ['move_joint','gripper','preset','software_stop'])assert.equal((await post('/api/v1/control/command',{...command,commandId:randomUUID(),opcode})).status,403);
  assert.equal((await post('/api/v1/control/stop',browser)).status,403);
  assert.deepEqual(f.requests.filter(x=>x.purpose==='command').map(x=>x.opcode),['connect']);
});
