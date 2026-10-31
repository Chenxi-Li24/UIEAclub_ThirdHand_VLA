'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {once}=require('node:events');
const {randomUUID}=require('node:crypto');
const {WebSocket}=require('ws');
const {controlFixture}=require('./control-fixture');
const {createCloudApi}=require('../../../services/cloud-api/src/server');

test('control WebSocket requires exact Origin, current cookie and CSRF bind; HTTP lease is tied to that connection',async t=>{
  const f=await controlFixture(t),origin='https://thirdhand.example.invalid';
  const server=createCloudApi({...f,publicOrigin:origin,controlService:f.service,controlChannels:f.channels});
  t.after(async()=>{await server.controlChannel?.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}`,url=base.replace('http','ws')+'/stream/v1/control',cookie=f.cookieFor(f.first);
  await assert.rejects(once(new WebSocket(url,{headers:{Origin:'https://attacker.invalid',Cookie:cookie}}),'open'));
  const socket=new WebSocket(url,{headers:{Origin:origin,Cookie:cookie}});await once(socket,'open');t.after(()=>socket.terminate());
  const clientInstanceId=randomUUID(),messages=[];socket.on('message',raw=>messages.push(JSON.parse(raw)));
  socket.send(JSON.stringify({type:'bind',clientInstanceId,csrfToken:f.first.csrfToken}));
  const deadline=Date.now()+3000;while(!messages.some(x=>x.type==='challenge')&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,5));
  const welcome=messages.find(x=>x.type==='bound'),challenge=messages.find(x=>x.type==='challenge');assert.ok(welcome);assert.ok(challenge);
  socket.send(JSON.stringify({type:'response',connectionId:welcome.connectionId,sequence:challenge.sequence,nonce:challenge.nonce}));
  await new Promise(resolve=>setTimeout(resolve,30));
  const response=await fetch(base+'/api/v1/control/lease',{method:'POST',headers:{Cookie:cookie,Origin:origin,'content-type':'application/json','x-csrf-token':f.first.csrfToken},body:JSON.stringify({deviceId:f.deviceId,clientInstanceId,connectionId:welcome.connectionId})});
  assert.equal(response.status,200);assert.equal((await response.json()).state,'active');
  const closed=once(socket,'close');
  socket.send(JSON.stringify({type:'response',connectionId:welcome.connectionId,sequence:challenge.sequence,nonce:challenge.nonce}));
  await closed;await f.service.drain();assert.equal(f.requests.at(-1).purpose,'stop');
});
