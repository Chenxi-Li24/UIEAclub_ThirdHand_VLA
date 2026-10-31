'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {createCameraClient}=require('../../../apps/web/public/js/camera-view');
test('camera viewing is explicit, video-only and independent of SDK/voice; stopping clears the private media grant',async()=>{
  const calls=[],video={srcObject:null,requestVideoFrameCallback(){return 1;},cancelVideoFrameCallback(){},pause(){}},view={location:{protocol:'https:',host:'thirdhand.example.invalid'},performance:{now:()=>0}};
  class FakeRoom extends EventEmitter{async connect(url,token){calls.push({kind:'connect',url,token});}async disconnect(){calls.push({kind:'disconnect'});}}
  const room=new FakeRoom(),request=async(path,body)=>{calls.push({path,body});return path==='/api/v1/media/close'?{closed:true}:{viewerId:'viewer-fixture',token:'private-test-token',serverUrl:'/media',publisherIdentity:'p_fixture'};};
  const client=createCameraClient({view,sessionClient:{request},video,createRoom:()=>room});assert.equal(calls.length,0);
  await client.watch('device-fixture');assert.equal(calls[0].path,'/api/v1/media/view');assert.equal(calls[1].url,'wss://thirdhand.example.invalid/media');
  const attached=[],track={kind:'video',attach:element=>attached.push(element),detach(){}};room.emit('trackSubscribed',track,{}, {identity:'p_fixture'});assert.deepEqual(attached,[video]);
  await client.close();assert.ok(calls.some(call=>call.path==='/api/v1/media/close'));assert.ok(calls.some(call=>call.kind==='disconnect'));assert.equal(video.srcObject,null);
  assert.ok(!calls.some(call=>/sdk|control|voice|microphone/.test(call.path||'')));
});
