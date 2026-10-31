'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {randomUUID,randomBytes,generateKeyPairSync}=require('node:crypto');
const {createLiveKitProvider}=require('../../../services/cloud-api/src/media/livekit-provider');
const {createMediaService}=require('../../../services/cloud-api/src/media/policy');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');

function fixture(t){
  const clock={value:Date.now(),mono:0,now(){return this.value;},monotonic(){return this.mono;}},events=new EventEmitter();
  const context={deviceId:randomUUID(),bootId:randomUUID(),executorEpoch:null,connectionId:randomUUID(),certificateId:randomUUID()},devices={get:id=>id===context.deviceId?context:null,events:new EventEmitter()};
  const identity={userId:randomUUID(),sessionId:randomUUID(),role:'observer',mode:'observe'},sessions={events,resolveSession:async request=>request.current};
  let unavailable=false;const removed=[],tokens=new Map(),provider={async viewToken({identity,room}){const token=randomUUID();tokens.set(token,{sub:identity,video:{room,roomJoin:true,canSubscribe:true,canPublish:false,canPublishData:false,canUpdateOwnMetadata:false}});return token;},async publisherToken({identity,room}){return 'publisher-only:'+identity+':'+room;},async verifyToken(token){if(!tokens.has(token))throw Error();return tokens.get(token);},async removeParticipant(room,identity){removed.push({room,identity});if(unavailable)throw Error('SFU unavailable');}};
  const keys=generateKeyPairSync('ed25519'),signer=createEnvelopeSigner({keyId:'media-test',privateKey:keys.privateKey});
  const service=createMediaService({sessions,devices,provider,signer,clock,startTimer:false});t.after(()=>service.close());
  const publisherId=randomUUID();let sequence=0;
  const report=(frame=null)=>service.acceptPublisher(context,{publisherId,sequence:++sequence,frame});
  const frame=(id='1')=>({frameId:id,capturedAtUs:String(BigInt(clock.value)*1000n),clockQuality:'synchronized',uncertaintyMs:1});
  return {service,clock,context,identity,events,removed,tokens,report,frame,setUnavailable:value=>unavailable=value};
}
test('real LiveKit grants are video-subscribe only for both human roles; publisher token cannot be obtained through viewer policy',async t=>{
  const provider=createLiveKitProvider({apiKey:'test-key',apiSecret:randomBytes(32).toString('hex'),host:'http://127.0.0.1:7880'});
  const token=await provider.viewToken({room:'device-test-room',identity:'v_'+randomUUID()}),claims=await provider.verifyToken(token);
  assert.equal(claims.video.canPublish,false);assert.equal(claims.video.canPublishData,false);assert.equal(claims.video.canSubscribe,true);assert.equal(claims.video.canUpdateOwnMetadata,false);assert.ok(claims.exp-Math.floor(Date.now()/1000)<=31);
  const f=fixture(t);await f.report(f.frame());
  for(const principal of [f.identity,{...f.identity,role:'admin',mode:'admin',mfaVerifiedAt:new Date()}]){const grant=await f.service.issueViewGrant(principal,{current:principal},{deviceId:f.context.deviceId});assert.ok(grant.token);assert.equal(grant.publisherToken,undefined);}
  await assert.rejects(f.service.issueViewGrant(null,{current:null},{deviceId:f.context.deviceId}),{code:'FORBIDDEN'});
});
test('logout denies cached/refreshed viewer rejoin and holds upstream publishing when SFU revocation fails',async t=>{
  const f=fixture(t);await f.report(f.frame());const request={current:f.identity},grant=await f.service.issueViewGrant(f.identity,request,{deviceId:f.context.deviceId});
  assert.equal((await f.service.authorizeSignaling(grant.token,f.identity)).kind,'viewer');
  f.setUnavailable(true);request.current=null;f.events.emit('revoked',{sessionId:f.identity.sessionId});
  await assert.rejects(f.service.authorizeSignaling(grant.token,f.identity),{code:'FORBIDDEN'});
  await assert.rejects(f.report(f.frame('2')),{code:'MEDIA_REVOCATION_PENDING'});await f.service.drain();assert.ok(f.removed.length>0);
  assert.equal(f.service.videoReadiness(f.identity,f.context.deviceId),false);
});

test('a real camera JWT authorizes only its live publisher and loses signaling access when that device disconnects',async t=>{
  const provider=createLiveKitProvider({apiKey:'test-camera-key',apiSecret:randomBytes(32).toString('hex'),host:'http://127.0.0.1:7880'});
  provider.ensureRoom=async()=>{};
  const context={deviceId:randomUUID(),bootId:randomUUID(),executorEpoch:null,connectionId:randomUUID(),certificateId:randomUUID()};
  let connected=true;const devices={get:()=>connected?context:null,events:new EventEmitter()},sessions={events:new EventEmitter(),resolveSession:async()=>null};
  const signer=createEnvelopeSigner({keyId:'camera-test',privateKey:generateKeyPairSync('ed25519').privateKey});
  const service=createMediaService({sessions,devices,provider,signer,startTimer:false});t.after(()=>service.close());
  const envelope=await service.acceptPublisher(context,{publisherId:randomUUID(),sequence:1,frame:null}),payload=JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));
  assert.equal((await service.authorizeSignaling(payload.token,null)).kind,'publisher');
  connected=false;devices.events.emit('disconnected',context);
  await assert.rejects(service.authorizeSignaling(payload.token,null),{code:'FORBIDDEN'});
});
test('fresh publisher frames plus matching rendered-frame acknowledgements are required; boolean cameraReady or replay cannot renew freshness',async t=>{
  const f=fixture(t),frame=f.frame();await f.report(frame);const grant=await f.service.issueViewGrant(f.identity,{current:f.identity},{deviceId:f.context.deviceId});
  assert.equal(f.service.videoReadiness(f.identity,f.context.deviceId),false);
  await assert.rejects(f.service.reportViewFrame(f.identity,{viewerId:grant.viewerId,cameraReady:true}),{code:'INVALID_INPUT'});
  await f.service.reportViewFrame(f.identity,{viewerId:grant.viewerId,frameId:frame.frameId,capturedAtUs:frame.capturedAtUs});assert.equal(f.service.videoReadiness(f.identity,f.context.deviceId),true);
  f.clock.mono+=600;f.clock.value+=600;
  await f.report(frame);await assert.rejects(f.service.reportViewFrame(f.identity,{viewerId:grant.viewerId,frameId:frame.frameId,capturedAtUs:frame.capturedAtUs}),{code:'STALE_VIDEO_FRAME'});
  assert.equal(f.service.videoReadiness(f.identity,f.context.deviceId),false);
});
