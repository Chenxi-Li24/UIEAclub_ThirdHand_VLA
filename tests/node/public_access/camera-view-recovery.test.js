'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createCameraClient,mountCameraView}=require('../../../apps/web/public/js/camera-view');
const {parseHTML}=require('linkedom');
const flush=async()=>{for(let index=0;index<100;index++)await Promise.resolve();};
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function fixture(){
  let time=0,nextTimer=0,frameCallback=null;
  const timers=new Map(),calls=[],rooms=[],doc=new EventTarget(),view=new EventTarget();
  doc.visibilityState='visible';
  Object.assign(view,{document:doc,location:{protocol:'https:',host:'camera.example.invalid'},performance:{now:()=>time},setTimeout(fn,delay){const id=++nextTimer;timers.set(id,{fn,at:time+delay});return id;},clearTimeout(id){timers.delete(id);}});
  const video={srcObject:null,pause(){calls.push({kind:'pause'});},requestVideoFrameCallback(fn){frameCallback=fn;return 1;},cancelVideoFrameCallback(){frameCallback=null;}};
  const identity={userId:'user-fixture',sessionId:'session-fixture',mode:'observe'};
  let views=0;
  const source={identity,async load(){calls.push({kind:'auth'});return {...source.identity};},async request(path,body){
    calls.push({path,body});if(path==='/api/v1/media/close')return {closed:true};
    if(path==='/api/v1/media/view'){views++;return {viewerId:`viewer-${views}`,deviceId:body.deviceId,serverUrl:'/media',publisherIdentity:`publisher-${views}`,token:`test-private-token-${views}`};}
    if(path==='/api/v1/media/frame')return {accepted:true};throw Error('Unexpected camera request');
  }};
  class Room extends EventEmitter{constructor(){super();this.number=rooms.length+1;}async connect(url,token){calls.push({kind:'connect',room:this.number,url,token});}async disconnect(){calls.push({kind:'disconnect',room:this.number});}}
  const states=[],client=createCameraClient({view,sessionClient:source,video,onChange:state=>states.push(state),createRoom(){const room=new Room();rooms.push(room);return room;}});
  return {client,view,doc,source,video,calls,rooms,states,timers,viewCount:()=>views,async advance(ms){const end=time+ms;for(;;){await flush();const next=[...timers].filter(([,value])=>value.at<=end).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;time=next[1].at;timers.delete(next[0]);next[1].fn();}time=end;await flush();},render(){const fn=frameCallback;frameCallback=null;fn?.(time,{});},track(identity=`publisher-${rooms.length}`){const incoming={kind:'video',attach(){video.srcObject={};calls.push({kind:'attach',identity});},detach(){calls.push({kind:'detach',identity});}};rooms.at(-1).emit('trackSubscribed',incoming,{}, {identity});return incoming;}};
}
test('publisher disconnect obtains a new authenticated viewer only after old room and viewer have closed',async()=>{
  const f=fixture();await f.client.watch('device-fixture');f.track();
  const close=deferred(),disconnect=deferred(),request=f.source.request;
  f.source.request=async(path,body)=>path==='/api/v1/media/close'?(f.calls.push({path,body}),close.promise):request(path,body);
  f.rooms[0].disconnect=()=>{f.calls.push({kind:'disconnect',room:1});return disconnect.promise;};
  f.rooms[0].emit('disconnected');await f.advance(1000);assert.equal(f.viewCount(),1,'old teardown is not acknowledged');
  disconnect.resolve();await flush();assert.equal(f.viewCount(),1,'old viewer is not revoked yet');
  close.resolve({closed:true});await flush();assert.equal(f.viewCount(),2,'watch intent recovers without another click');
  assert.equal(f.calls.filter(call=>call.kind==='auth').length,1);
  f.track('publisher-1');assert.equal(f.video.srcObject,null,'old publisher identity cannot attach in new room');
  f.track('publisher-2');assert.ok(f.video.srcObject);f.rooms[0].emit('disconnected');await f.advance(1000);assert.equal(f.viewCount(),2,'late old room events cannot restart the new viewer');
  await f.client.close();
});
test('unavailable camera retries finitely and never starts itself before an explicit watch',async()=>{
  const f=fixture(),request=f.source.request;f.source.request=async(path,body)=>{if(path==='/api/v1/media/view'){f.calls.push({path,body});throw Object.assign(Error('MEDIA_UNAVAILABLE'),{code:'MEDIA_UNAVAILABLE'});}return request(path,body);};
  await f.advance(100000);assert.equal(f.calls.length,0);await assert.rejects(f.client.watch('device-fixture'),{code:'MEDIA_UNAVAILABLE'});
  await f.advance(100000);assert.equal(f.calls.filter(call=>call.path==='/api/v1/media/view').length,7,'one explicit attempt and at most six recovery attempts');assert.equal(f.timers.size,0);assert.equal(f.client.state(),'unavailable');
  assert.ok(f.calls.every(call=>!call.path||/^\/api\/v1\/media\//.test(call.path)));
});
test('Close during initial cleanup cancels the queued watch before any viewer is created',async()=>{
  const f=fixture(),watching=f.client.watch('device-fixture');await f.client.close();await watching;assert.equal(f.viewCount(),0);await f.advance(100000);assert.equal(f.viewCount(),0);
});
test('a grant arriving after Close is revoked without connecting and cannot schedule recovery',async()=>{
  const f=fixture(),pending=deferred(),request=f.source.request;f.source.request=async(path,body)=>path==='/api/v1/media/view'?(f.calls.push({path,body}),pending.promise):request(path,body);
  const watching=f.client.watch('device-fixture');await flush();await f.client.close();pending.resolve({viewerId:'late-viewer',serverUrl:'/media',publisherIdentity:'late-publisher',token:'test-late-token'});await watching;await f.advance(100000);
  assert.equal(f.rooms.length,0);assert.equal(f.calls.filter(call=>call.path==='/api/v1/media/close').length,1);assert.equal(f.timers.size,0);
});
test('an unknown in-flight grant blocks another explicit watch even after the local authorization timeout',async()=>{
  const f=fixture(),pending=deferred(),request=f.source.request;let requests=0;
  f.source.request=async(path,body)=>path==='/api/v1/media/view'&&++requests===1?pending.promise:request(path,body);
  const watching=f.client.watch('device-fixture'),failed=assert.rejects(watching,{code:'CAMERA_TIMEOUT'});await flush();await f.advance(12000);await failed;
  assert.equal(f.client.state(),'unavailable');await assert.rejects(f.client.watch('device-fixture'),{code:'MEDIA_BUSY'});assert.equal(requests,1,'unknown old grant cannot overlap a new viewer');
  pending.resolve({viewerId:'late-timeout-viewer',serverUrl:'/media',publisherIdentity:'late-publisher',token:'test-late-token'});await flush();assert.equal(f.rooms.length,0);assert.equal(f.calls.filter(call=>call.path==='/api/v1/media/close').length,1);
  await f.client.watch('device-fixture');assert.equal(f.rooms.length,1);await f.client.close();
});
for(const event of ['visibilitychange','pagehide'])test(`${event} detaches immediately and requires another explicit watch even after visibility returns`,async()=>{
  const f=fixture();await f.client.watch('device-fixture');f.track();
  if(event==='visibilitychange'){f.doc.visibilityState='hidden';f.doc.dispatchEvent(new Event(event));}else f.view.dispatchEvent(new Event(event));
  assert.equal(f.video.srcObject,null);f.doc.visibilityState='visible';f.doc.dispatchEvent(new Event('visibilitychange'));await f.advance(100000);assert.equal(f.viewCount(),1);assert.equal(f.client.state(),'unavailable');
});
test('failed or unconfirmed viewer revocation never obtains a replacement grant',async()=>{
  for(const behavior of ['reject','unconfirmed','timeout']){
    const f=fixture(),request=f.source.request;await f.client.watch('device-fixture');
    f.source.request=async(path,body)=>{if(path==='/api/v1/media/close'){if(behavior==='reject')throw Error('network failure');if(behavior==='unconfirmed')return {closed:false};return new Promise(()=>{});}return request(path,body);};
    f.rooms[0].emit('disconnected');await f.advance(100000);assert.equal(f.viewCount(),1,behavior);assert.equal(f.client.state(),'unavailable',behavior);assert.equal(f.timers.size,0,behavior);
  }
});
test('revoked or changed sessions terminate recovery before requesting another media grant',async()=>{
  for(const behavior of ['revoked','changed']){
    const f=fixture();await f.client.watch('device-fixture');f.source.load=async()=>{if(behavior==='revoked')throw Object.assign(Error('UNAUTHENTICATED'),{code:'UNAUTHENTICATED'});return {userId:'other-user',sessionId:'other-session',mode:'observe'};};
    f.rooms[0].emit('disconnected');await f.advance(100000);assert.equal(f.viewCount(),1,behavior);assert.equal(f.client.state(),'unavailable');assert.equal(f.timers.size,0);
  }
});
test('a denied view grant is terminal and dispose prevents even a later explicit watch',async()=>{
  const f=fixture();f.source.request=async(path,body)=>{f.calls.push({path,body});throw Object.assign(Error('FORBIDDEN'),{code:'FORBIDDEN'});};
  await assert.rejects(f.client.watch('device-fixture'),{code:'FORBIDDEN'});await f.advance(100000);assert.equal(f.calls.filter(call=>call.path).length,1);assert.equal(f.client.state(),'unavailable');await f.client.dispose();await assert.rejects(f.client.watch('device-fixture'),{code:'CAMERA_UNAVAILABLE'});
});
test('a connected room without decoded frames is replaced and occasional frames do not reset the retry bound',async()=>{
  const f=fixture();await f.client.watch('device-fixture');
  for(let attempt=0;attempt<7;attempt++){
    f.track();f.render();await f.advance(12000);f.client.checkFreshness();await f.advance(10000);
  }
  assert.equal(f.viewCount(),7);assert.equal(f.client.state(),'unavailable');assert.equal(f.timers.size,0);await f.advance(100000);assert.equal(f.viewCount(),7);
});
test('the mounted Sign out button immediately stops camera intent before navigation or logout finishes',async()=>{
  const f=fixture(),{document,window}=parseHTML('<html><body><button id="workspace-logout">Sign out</button><section id="sec-xvision"><div class="sec-body"><span id="cam-label"></span><span id="cam-dot"></span><div><img id="xvision-feed"><div class="camera-empty"></div></div></div></section></body></html>');
  f.view.document=document;document.visibilityState='visible';f.view.setInterval=()=>1;f.view.clearInterval=()=>{};
  f.view.LivekitClient={Room:class extends EventEmitter{constructor(){super();f.rooms.push(this);}async connect(){}async disconnect(){}}};
  const mounted=mountCameraView({view:f.view,document,sessionClient:f.source});await mounted.client.watch('device-fixture');const video=document.querySelector('video');
  f.rooms[0].emit('trackSubscribed',{kind:'video',attach(){video.srcObject={};},detach(){}},{},{identity:'publisher-1'});assert.ok(video.srcObject);
  document.getElementById('workspace-logout').dispatchEvent(new window.Event('click'));assert.equal(video.srcObject,null);await f.advance(100000);assert.equal(f.viewCount(),1);assert.equal(mounted.client.state(),'unavailable');mounted.dispose();
});
