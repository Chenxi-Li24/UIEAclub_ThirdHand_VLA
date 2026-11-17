'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {createAdminControlClient}=require('../../../apps/web/public/js/admin-control');

function fixture(identity={role:'admin',mode:'admin',csrfToken:'csrf-test'}){
  const sockets=[],requests=[];let time=1000;
  class Socket{constructor(url){this.url=url;this.sent=[];sockets.push(this);}send(value){this.sent.push(JSON.parse(value));}close(){this.onclose?.();}receive(value){this.onmessage?.({data:JSON.stringify(value)});}}
  const view={location:{protocol:'https:',host:'thirdhand.example.invalid'},WebSocket:Socket,crypto:{randomUUID},performance:{now:()=>time}};
  const sessionClient={async request(path,body,options){requests.push({path,body,options});if(path.endsWith('/lease'))return {id:randomUUID(),state:'active',leaseEpoch:1};if(path.endsWith('/command'))return {state:'completed',commandId:body.commandId};if(path.includes('/status'))return {lease:{leaseEpoch:1,state:'active'}};if(path.endsWith('takeover-request'))return {requestId:randomUUID(),nonce:'n'.repeat(43),requiresConfirmation:true,holderName:'Test holder'};return {state:'stopped'};}};
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

test('only negotiated observation channels accept a delayed ACK, without extending its original age',async()=>{
  const f=fixture({role:'observer',mode:'observe'}),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId,freshnessMs:3000});
  ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});
  f.advance(1200);ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  await f.client.acquire(randomUUID());assert.equal(f.client.state().lease.state,'active');
  await assert.rejects(f.client.command('move_joint',{}),{code:'FORBIDDEN'});
  f.advance(1800);await assert.rejects(f.client.command('connect',{}),{code:'BROWSER_STALE'});
  assert.equal(f.requests.length,1,'neither initialization nor motion is automatic');
  for(const identity of [{role:'admin',mode:'admin'},{role:'observer',mode:'observe'}]){
    const bad=fixture(identity),pending=bad.client.open(),socket=bad.sockets[0];socket.onopen();
    socket.receive({type:'bound',connectionId:randomUUID(),freshnessMs:identity.mode==='admin'?3000:3001});
    await assert.rejects(pending,{code:'CONTROL_PROTOCOL_ERROR'});
  }
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

test('a pending authorization cannot create a second request or change selected device',async()=>{
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  let finish,calls=0;f.sessionClient.request=()=>{calls++;return new Promise(resolve=>{finish=resolve;});};
  const id=randomUUID(),first=f.client.acquire(id);await new Promise(setImmediate);
  await assert.rejects(f.client.acquire(randomUUID()),{code:'REQUEST_IN_PROGRESS'});
  assert.equal(calls,1);assert.equal(f.client.state().deviceId,id);
  finish({id:randomUUID(),state:'active',leaseEpoch:1});await first;f.client.close();
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

async function authorizedFixture(){
  const f=fixture(),opening=f.client.open(),ws=f.sockets[0],connectionId=randomUUID();ws.onopen();
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  await f.client.acquire(randomUUID());return f;
}

test('only explicit SDK connection commands extend the session request deadline beyond the device ACK window',async()=>{
  const f=await authorizedFixture();
  await f.client.command('connect',{});await f.client.command('move_joint',{});await f.client.command('disconnect',{});
  assert.deepEqual(f.requests.map(({body,options})=>[body.opcode||'lease',options]),[
    ['lease',undefined],['connect',{timeoutMs:40000}],['move_joint',undefined],['disconnect',{timeoutMs:40000}]
  ]);
  f.client.close();
});

test('post-submission timeout, disconnect and unknown receipts stay ambiguous with only safe reason codes and no retry',async()=>{
  for(const [reply,want]of [
    [Object.assign(Error('private upstream detail'),{code:'REQUEST_TIMEOUT',cause:'private cause'}),'REQUEST_TIMEOUT'],
    [Object.assign(Error('private upstream detail'),{code:'CONTROL_DISCONNECTED'}),'CONTROL_DISCONNECTED'],
    [Object.assign(Error('private upstream detail'),{code:'PRIVATE_UPSTREAM_CODE'}),undefined],
    [{state:'unknown',code:'SUBMISSION_RESULT_UNKNOWN'},'SUBMISSION_RESULT_UNKNOWN'],
    [{state:'unknown',code:'PRIVATE_UPSTREAM_CODE',reasonCode:'ROBOT_REJECTED'},undefined]
  ]){
    const f=await authorizedFixture();let submissions=0;
    f.sessionClient.request=async()=>{submissions++;if(reply instanceof Error)throw reply;return reply;};
    await assert.rejects(f.client.command('connect',{}),error=>{
      assert.equal(error.code,'COMMAND_RESULT_UNKNOWN');assert.equal(error.reasonCode,want);
      assert.equal(error.cause,undefined);assert.doesNotMatch(error.message,/private|PRIVATE_UPSTREAM_CODE/);return true;
    });
    assert.equal(submissions,1);assert.equal(f.client.state().lease,null);assert.equal(f.client.state().connected,false);
  }
});

test('policy denials retain known rejection classification instead of claiming an unknown device result',async()=>{
  for(const code of ['FORBIDDEN','BROWSER_STALE','LEASE_CHANGED','LEASE_REQUIRED','INVALID_INPUT','COMMAND_ID_CONFLICT','CONTROL_READINESS_REQUIRED','READ_ONLY_DEVICE']){
    const f=await authorizedFixture();
    f.sessionClient.request=async()=>{throw Object.assign(Error('private rejection detail'),{code,cause:'private cause'});};
    await assert.rejects(f.client.command('connect',{}),error=>{
      assert.equal(error.code,code);assert.equal(error.cause,undefined);assert.doesNotMatch(error.message,/private/);return true;
    });
  }
});

test('device rejection and failure receipts expose only allowlisted reasonCode values',async()=>{
  for(const state of ['rejected','failed'])for(const [code,want]of [['ROBOT_REJECTED','ROBOT_REJECTED'],['READ_ONLY_DEVICE','READ_ONLY_DEVICE'],['ROBOT_BUSY','ROBOT_BUSY'],['LEASE_NOT_READY','LEASE_NOT_READY'],['PRIVATE_UPSTREAM_CODE',undefined],['<secret>',undefined]]){
    const f=await authorizedFixture();
    f.sessionClient.request=async()=>({state,code,reasonCode:'FORGED_REASON_CODE'});
    const result=await f.client.command('connect',{});
    assert.equal(result.state,state);assert.equal(result.reasonCode,want);assert.equal(result.code,undefined);
    f.client.close();
  }
});

test('missing or unrecognized command receipts remain unknown instead of retaining authorization',async()=>{
  for(const reply of [null,{}, {state:'PRIVATE_UPSTREAM_STATE',code:'PRIVATE_UPSTREAM_CODE'}]){
    const f=await authorizedFixture();let submissions=0;
    f.sessionClient.request=async()=>{submissions++;return reply;};
    await assert.rejects(f.client.command('connect',{}),error=>{assert.equal(error.code,'COMMAND_RESULT_UNKNOWN');assert.equal(error.reasonCode,undefined);return true;});
    assert.equal(submissions,1);assert.equal(f.client.state().lease,null);
  }
});
