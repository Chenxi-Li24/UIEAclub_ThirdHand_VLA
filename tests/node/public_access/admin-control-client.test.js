'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createAdminControlClient}=require('../../../apps/web/public/js/admin-control');

function fixture(identity={role:'admin',mode:'admin',csrfToken:'csrf-test'}){
  const sockets=[],requests=[];let time=1000;
  class Socket{constructor(url){this.url=url;this.sent=[];sockets.push(this);}send(value){this.sent.push(JSON.parse(value));}close(){this.onclose?.();}receive(value){this.onmessage?.({data:JSON.stringify(value)});}}
  const view={location:{protocol:'https:',host:'thirdhand.example.invalid'},WebSocket:Socket,crypto:{randomUUID},performance:{now:()=>time}};
  const sessionClient={async request(path,body){requests.push({path,body});if(path.endsWith('/lease'))return {id:randomUUID(),state:'active',leaseEpoch:1};if(path.endsWith('/command'))return {state:'completed',commandId:body.commandId};if(path.includes('/status'))return {lease:{leaseEpoch:1,state:'active'}};if(path.endsWith('takeover-request'))return {requestId:randomUUID(),nonce:'n'.repeat(43),requiresConfirmation:true,holderName:'Test holder'};return {state:'stopped'};}};
  const client=createAdminControlClient({view,identity,sessionClient});
  return {client,sockets,requests,sessionClient,advance:ms=>{time+=ms;}};
}

test('batched challenges accept an earlier valid ACK without closing the channel',async()=>{
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId});
  ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});
  f.advance(250);ws.receive({type:'challenge',connectionId,sequence:2,nonce:'y'.repeat(43)});
  ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  assert.equal(f.client.state().connected,true);
  ws.receive({type:'fresh',connectionId,sequence:2});
  await f.client.acquire(randomUUID());assert.equal(f.client.state().lease.state,'active');
  assert.equal(f.requests.some(r=>r.path.endsWith('/command')),false);f.client.close();
});

test('delayed ACK cannot reset the freshness clock and forged or replayed ACKs fail closed',async()=>{
  for(const kind of ['expired','unknown','replay']){
    const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
    ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});
    ws.receive({type:'fresh',connectionId,sequence:1});await opening;
    if(kind==='expired'){
      f.advance(250);ws.receive({type:'challenge',connectionId,sequence:2,nonce:'y'.repeat(43)});f.advance(500);
      ws.receive({type:'fresh',connectionId,sequence:2});
    }else ws.receive({type:'fresh',connectionId,sequence:kind==='unknown'?99:1});
    assert.equal(f.client.state().connected,false);assert.equal(f.requests.length,0);
  }
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});
  f.advance(400);ws.receive({type:'fresh',connectionId,sequence:1});await opening;f.advance(100);
  await assert.rejects(f.client.command('connect',{}),{code:'LEASE_REQUIRED'});
  const reopened=f.client.open();assert.equal(f.sockets.length,2,'ACK receipt must not extend its response age');
  f.client.close();await assert.rejects(reopened,{code:'CONTROL_DISCONNECTED'});
});

test('an HTTP lease result arriving after socket closure cannot restore a disconnected lease',async()=>{
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  let resolve;f.sessionClient.request=()=>new Promise(done=>{resolve=done;});
  const acquisition=f.client.acquire(randomUUID());await new Promise(done=>setImmediate(done));ws.close();
  resolve({id:randomUUID(),state:'active',leaseEpoch:1});await assert.rejects(acquisition,{code:'BROWSER_STALE'});
  assert.equal(f.client.state().lease,null);assert.equal(f.client.state().connected,false);
});

test('administrator opens only a protected control channel; lease and SDK command require separate explicit actions',async()=>{
  const f=fixture();assert.equal(f.sockets.length,0);assert.equal(f.requests.length,0);
  const opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  assert.match(ws.url,/^wss:\/\/thirdhand\.example\.invalid\/stream\/v1\/control$/);
  assert.equal(ws.sent[0].type,'bind');assert.equal(f.requests.length,0);
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});
  assert.equal(ws.sent.at(-1).type,'response');ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  assert.equal(f.requests.length,0);
  await assert.rejects(f.client.command('connect',{}),{code:'LEASE_REQUIRED'});
  await f.client.acquire(randomUUID());assert.equal(f.requests.length,1);assert.ok(f.requests[0].path.endsWith('/lease'));
  await f.client.command('connect',{});assert.equal(f.requests[1].body.opcode,'connect');
  ws.close();await assert.rejects(f.client.command('connect',{}),{code:'LEASE_REQUIRED'});
  assert.equal(f.sockets.length,1,'closed channel must not automatically reconnect');
});

test('observer sessions can connect but cannot send motion, stop other owners or take over',async()=>{
  for(const identity of [{role:'observer',mode:'observe'},{role:'admin',mode:'observe'}]){
    const f=fixture(identity),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
    ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
    await f.client.acquire(randomUUID());await f.client.command('connect',{});
    for(const opcode of ['move_joint','gripper','preset','software_stop'])await assert.rejects(f.client.command(opcode,{}),{code:'FORBIDDEN'});
    await assert.rejects(f.client.stop(),{code:'FORBIDDEN'});await assert.rejects(f.client.prepareTakeover(randomUUID()),{code:'FORBIDDEN'});
    assert.deepEqual(f.requests.map(r=>r.body.opcode).filter(Boolean),['connect']);f.client.close();
  }
});

test('takeover stays a warning until explicit confirmation and model edits have no network method',async()=>{
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  const warning=await f.client.prepareTakeover(randomUUID());assert.equal(warning.requiresConfirmation,true);
  assert.equal(f.requests.some(x=>x.path.endsWith('takeover-confirm')),false);
  f.client.cancelTakeover();await assert.rejects(f.client.confirmTakeover(),{code:'TAKEOVER_INVALID'});
  assert.equal(typeof f.client.setJoints,'undefined');
});
