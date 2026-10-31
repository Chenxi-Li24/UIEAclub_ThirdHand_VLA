'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const http=require('node:http');
const {EventEmitter,once}=require('node:events');
const {randomUUID}=require('node:crypto');
const {WebSocket}=require('ws');
const {createBrowserControlRegistry}=require('../../../services/cloud-api/src/control/control-channel');
const {createControlWebSocket}=require('../../../services/cloud-api/src/control/websocket');

function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};}
async function fixture(t){
  const principal={userId:randomUUID(),sessionId:randomUUID(),role:'admin',mode:'admin',roleVersion:1,mfaVerifiedAt:new Date()};
  const clock={value:1000,monotonic(){return this.value;}};
  const channels=createBrowserControlRegistry({clock}),events=new EventEmitter();
  let hold=null,valid=true;
  const sessions={events,verifyCsrf:()=>true,async resolveSession(){if(hold){const current=hold;current.started.resolve();await current.release.promise;}return valid?principal:null;}};
  const origin='https://thirdhand.example.invalid';
  const timings=[];
  const control=createControlWebSocket({sessions,channels,publicOrigin:origin,onTiming:value=>timings.push(value)});
  let transportSocket;
  const server=http.createServer();server.on('connection',socket=>{transportSocket=socket;});server.on('upgrade',(request,socket,head)=>void control.upgrade(request,socket,head));
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const socket=new WebSocket(`ws://127.0.0.1:${server.address().port}/stream/v1/control`,{headers:{Origin:origin}});
  const messages=[],changed=new EventEmitter();let closed=false;
  socket.on('message',raw=>{messages.push(JSON.parse(raw));changed.emit('change');});
  socket.on('close',()=>{closed=true;changed.emit('change');});
  t.after(async()=>{hold?.release.resolve();socket.terminate();await control.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  await once(socket,'open');
  function waitFor(predicate){
    const current=messages.find(predicate);if(current)return Promise.resolve(current);
    return new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>finish(Error('Expected control message was not received')),1500);
      function finish(error,value){clearTimeout(timeout);changed.off('change',check);error?reject(error):resolve(value);}
      function check(){const found=messages.find(predicate);if(found)finish(null,found);else if(closed)finish(Error('Control socket closed before the expected fresh response'));}
      changed.on('change',check);check();
    });
  }
  socket.send(JSON.stringify({type:'bind',clientInstanceId:randomUUID(),csrfToken:'test-only'}));
  const bound=await waitFor(value=>value.type==='bound'),first=await waitFor(value=>value.type==='challenge');
  return {socket,channels,clock,bound,first,messages,waitFor,timings,
    block(){hold={started:deferred(),release:deferred()};return hold;},
    invalidate(){valid=false;},
    respond(value){socket.send(JSON.stringify({type:'response',connectionId:value.connectionId,sequence:value.sequence,nonce:value.nonce}));},
    async deliver(value){const received=once(transportSocket,'data');this.respond(value);await received;},
    get closed(){return closed;}};
}

test('two valid control responses delivered as a burst survive an in-flight identity check',async t=>{
  const f=await fixture(t),hold=f.block();
  f.respond(f.first);await hold.started.promise;
  const second=f.channels.challenge(f.bound.connectionId);
  await f.waitFor(value=>value.type==='challenge'&&value.sequence===second.sequence);
  await f.deliver(second);hold.release.resolve();
  await f.waitFor(value=>value.type==='fresh'&&value.sequence===second.sequence);
  assert.equal(f.closed,false);
  assert.deepEqual(f.messages.filter(value=>value.type==='fresh').map(value=>value.sequence),[f.first.sequence,second.sequence]);
  assert.equal(f.timings.filter(value=>value.stage==='browser_response'&&value.outcome==='accepted').length,2);
  const allowed=['traceId','stage','outcome','elapsedMs','queueMs','authMs','code'];
  for(const row of f.timings){assert.ok(Object.keys(row).every(key=>allowed.includes(key)));assert.ok(row.elapsedMs>=0&&row.queueMs>=0&&row.authMs>=0);}
  assert.equal(JSON.stringify(f.timings).includes(f.first.nonce),false);
});

test('a queued response still expires at the original 500ms challenge boundary',async t=>{
  const f=await fixture(t),hold=f.block();
  f.respond(f.first);await hold.started.promise;
  f.clock.value+=500;hold.release.resolve();
  await once(f.socket,'close');
  assert.equal(f.messages.some(value=>value.type==='fresh'),false);
});

test('identity revocation during queued authorization never acknowledges freshness',async t=>{
  const f=await fixture(t),hold=f.block();
  f.respond(f.first);await hold.started.promise;
  f.invalidate();hold.release.resolve();await once(f.socket,'close');
  assert.equal(f.messages.some(value=>value.type==='fresh'),false);
});

test('the serial response queue is bounded and rejects an authorization-time flood',async t=>{
  const f=await fixture(t),hold=f.block();
  f.respond(f.first);await hold.started.promise;
  const second=f.channels.challenge(f.bound.connectionId);
  f.respond(second);f.respond(second);await once(f.socket,'close');hold.release.resolve();
  assert.equal(f.messages.some(value=>value.type==='fresh'),false);
});

test('a rejected replay revokes browser authority before an unresponsive peer closes TCP',async t=>{
  const f=await fixture(t);
  f.respond(f.first);await f.waitFor(value=>value.type==='fresh');
  // A client may receive a close frame without completing the close handshake.
  // Authority must not remain live until the transport eventually disappears.
  f.socket.close=()=>{};
  const revoked=once(f.channels.events,'closed',{signal:AbortSignal.timeout(800)});
  f.respond(f.first);
  assert.equal((await revoked)[0].connectionId,f.bound.connectionId);
  assert.equal(f.closed,false);
});
