'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createAdminControlClient}=require('../../../apps/web/public/js/admin-control');

function fixture(identity={role:'admin',mode:'admin',csrfToken:'csrf-test'}){
  const sockets=[],requests=[];
  class Socket{constructor(url){this.url=url;this.sent=[];sockets.push(this);}send(value){this.sent.push(JSON.parse(value));}close(){this.onclose?.();}receive(value){this.onmessage?.({data:JSON.stringify(value)});}}
  const view={location:{protocol:'https:',host:'thirdhand.example.invalid'},WebSocket:Socket,crypto:{randomUUID},performance:{now:()=>1000}};
  const sessionClient={async request(path,body){requests.push({path,body});if(path.endsWith('/lease'))return {id:randomUUID(),state:'active',leaseEpoch:1};if(path.endsWith('/command'))return {state:'completed',commandId:body.commandId};if(path.includes('/status'))return {lease:{leaseEpoch:1,state:'active'}};if(path.endsWith('takeover-request'))return {requestId:randomUUID(),nonce:'n'.repeat(43),requiresConfirmation:true,holderName:'Test holder'};return {state:'stopped'};}};
  const client=createAdminControlClient({view,identity,sessionClient});
  return {client,sockets,requests};
}

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

test('observer or administrator in observer mode never opens control channel or issues SDK calls',async()=>{
  for(const identity of [{role:'observer',mode:'observe'},{role:'admin',mode:'observe'}]){
    const f=fixture(identity);await assert.rejects(f.client.open(),{code:'FORBIDDEN'});await assert.rejects(f.client.command('connect',{}));
    assert.equal(f.sockets.length,0);assert.equal(f.requests.length,0);
  }
});

test('takeover stays a warning until explicit confirmation and model edits have no network method',async()=>{
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  const warning=await f.client.prepareTakeover(randomUUID());assert.equal(warning.requiresConfirmation,true);
  assert.equal(f.requests.some(x=>x.path.endsWith('takeover-confirm')),false);
  f.client.cancelTakeover();await assert.rejects(f.client.confirmTakeover(),{code:'TAKEOVER_INVALID'});
  assert.equal(typeof f.client.setJoints,'undefined');
});
