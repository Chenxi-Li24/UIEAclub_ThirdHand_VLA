'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {randomUUID,generateKeyPairSync}=require('node:crypto');
const {createEnvelopeSigner,verifyEnvelope}=require('../../../services/device-relay/src/envelope');
const {createMediaService}=require('../../../services/cloud-api/src/media/policy');
let createMotionVideoBridge;
try{({createMotionVideoBridge}=require('../../../services/cloud-api/src/media/motion-video-bridge'));}catch(error){if(error.code!=='MODULE_NOT_FOUND')throw error;}

function fixture(){
  assert.equal(typeof createMotionVideoBridge,'function','motion source evidence bridge must exist');
  const clock={value:1793450000000,mono:0,now(){return this.value;},monotonic(){return this.mono;}};
  const context=()=>Object.fromEntries(['deviceId','bootId','executorEpoch','connectionId','certificateId'].map(key=>[key,randomUUID()]));
  const robot=context(),camera={...context(),executorEpoch:null};
  let currentRobot=robot;
  const devices={get:id=>id===robot.deviceId?currentRobot:null};
  const keys=generateKeyPairSync('ed25519');
  const frame={frameId:'1',capturedAtUs:String(BigInt(clock.value)*1000n),clockQuality:'estimated',uncertaintyMs:15};
  let source={context:camera,sourceFresh:true,frame};
  let binding={id:randomUUID(),state:'verified',robotDeviceId:robot.deviceId,cameraDeviceId:camera.deviceId,
    evidenceId:'onsite-camera-binding:1',expiresAt:clock.value+60000};
  const mediaService={motionSourceEvidence:()=>source};
  const bridge=createMotionVideoBridge({mediaService,devices,bindings:{getVerifiedBinding:async()=>binding},
    signer:createEnvelopeSigner({keyId:'motion-video-test',privateKey:keys.privateKey}),clock});
  return {clock,robot,camera,frame,bridge,keys,devices,setRobotContext:value=>{currentRobot=value;},setSource:value=>{source=value;},setBinding:value=>{binding=value;},
    source:()=>source,binding:()=>binding,issue:()=>bridge.issue({robotContext:robot,cameraContext:camera})};
}

test('motion video proof is bound to robot executor and camera source without transferring a media JWT',async()=>{
  const f=fixture(),envelope=await f.issue();
  const value=verifyEnvelope(envelope,new Map([['motion-video-test',f.keys.publicKey]]),f.robot,f.clock.value);
  assert.equal(value.purpose,'motion_video_health');assert.deepEqual(value.cameraContext,f.camera);
  assert.equal(value.cameraBindingId,f.binding().id);assert.equal(value.sourceFresh,true);assert.deepEqual(value.frame,f.frame);
  assert.ok(value.expiresAt-value.issuedAt<=950);assert.equal(value.sequence,1);
  for(const name of ['token','identity','room','principal','sessionId'])assert.equal(value[name],undefined);
  const next=verifyEnvelope(await f.issue(),new Map([['motion-video-test',f.keys.publicKey]]),f.robot,f.clock.value);
  assert.equal(next.sequence,2);
});

test('missing, expired, unverified or mismatched physical camera bindings cannot produce a motion proof',async()=>{
  for(const change of [null,{state:'pending'},{expiresAt:1793450000000},{robotDeviceId:randomUUID()},
    {cameraDeviceId:randomUUID()},{evidenceId:''}]){
    const f=fixture();f.setBinding(change===null?null:{...f.binding(),...change});
    await assert.rejects(f.issue(),{code:'MOTION_CAMERA_BINDING_REQUIRED'});
  }
});

test('wrong camera executor, reconnect, revoked source or unknown capture time remains unavailable',async()=>{
  for(const change of [null,{sourceFresh:false},{context:{connectionId:randomUUID()}},
    {frame:null},{frame:{clockQuality:'unreliable'}},{frame:{capturedAtUs:undefined}},{frame:{uncertaintyMs:NaN}}]){
    const f=fixture();
    const value=change===null?null:{...f.source(),...change,
      ...(change.context?{context:{...f.camera,...change.context}}:{}),
      ...(change.frame?{frame:{...f.frame,...change.frame}}:{})};
    f.setSource(value);await assert.rejects(f.issue(),{code:'MOTION_VIDEO_UNAVAILABLE'});
  }
});

test('capture age including uncertainty must fit the original 500ms budget',async()=>{
  for(const age of [486,501,-16]){
    const f=fixture();f.clock.value+=age;await assert.rejects(f.issue(),{code:'MOTION_VIDEO_UNAVAILABLE'});
  }
  const f=fixture();f.clock.value+=485;
  const envelope=await f.issue();assert.ok(envelope.signatureBase64url);
});

test('binding lookup delays are accounted for using the post-lookup clock',async()=>{
  const f=fixture();
  const bridge=createMotionVideoBridge({mediaService:{motionSourceEvidence:()=>f.source()},devices:f.devices,
    bindings:{getVerifiedBinding:async()=>{f.clock.value+=501;return f.binding();}},
    signer:createEnvelopeSigner({keyId:'delay-test',privateKey:f.keys.privateKey}),clock:f.clock});
  await assert.rejects(bridge.issue({robotContext:f.robot,cameraContext:f.camera}),{code:'MOTION_VIDEO_UNAVAILABLE'});
});

test('late async lookup cannot sign a source after it has been replaced',async()=>{
  const f=fixture();
  const bridge=createMotionVideoBridge({mediaService:{motionSourceEvidence:()=>f.source()},devices:f.devices,
    bindings:{getVerifiedBinding:async()=>{f.setSource(null);return f.binding();}},
    signer:createEnvelopeSigner({keyId:'revoke-test',privateKey:f.keys.privateKey}),clock:f.clock});
  await assert.rejects(bridge.issue({robotContext:f.robot,cameraContext:f.camera}),{code:'MOTION_VIDEO_UNAVAILABLE'});
});

test('old or disconnected robot executor cannot acquire a newly signed source proof',async()=>{
  for(const actual of [null,{executorEpoch:randomUUID()},{connectionId:randomUUID()},{certificateId:randomUUID()}]){
    const f=fixture();f.setRobotContext(actual===null?null:{...f.robot,...actual});
    await assert.rejects(f.issue(),{code:'MOTION_ROBOT_CONTEXT_CHANGED'});
  }
});

test('robot context is revalidated after asynchronous binding lookup',async()=>{
  const f=fixture();
  const bridge=createMotionVideoBridge({mediaService:{motionSourceEvidence:()=>f.source()},devices:f.devices,
    bindings:{getVerifiedBinding:async()=>{f.setRobotContext(null);return f.binding();}},
    signer:createEnvelopeSigner({keyId:'robot-revoke-test',privateKey:f.keys.privateKey}),clock:f.clock});
  await assert.rejects(bridge.issue({robotContext:f.robot,cameraContext:f.camera}),{code:'MOTION_ROBOT_CONTEXT_CHANGED'});
});

test('legitimate new executor instances of one device do not exhaust the bounded device counter',async()=>{
  const f=fixture();
  for(let index=0;index<65;index++){
    f.robot.executorEpoch=randomUUID();f.robot.connectionId=randomUUID();
    assert.ok((await f.issue()).signatureBase64url);
  }
});

test('media service exposes only current internal source evidence and no publishing token',async t=>{
  const clock={value:1793450000000,mono:0,now(){return this.value;},monotonic(){return this.mono;}},
    camera={deviceId:randomUUID(),bootId:randomUUID(),executorEpoch:null,connectionId:randomUUID(),certificateId:randomUUID()};
  let active=true;
  const sessions={events:new EventEmitter(),resolveSession:async()=>null},devices={events:new EventEmitter(),get:()=>active?camera:null};
  const media=createMediaService({sessions,devices,clock,startTimer:false,
    provider:{publisherToken:async()=>'private-publish-token',removeParticipant:async()=>{}},
    signer:createEnvelopeSigner({keyId:'source-test',privateKey:generateKeyPairSync('ed25519').privateKey})});
  t.after(()=>media.close());assert.equal(typeof media.motionSourceEvidence,'function');
  assert.equal(media.motionSourceEvidence(camera.deviceId),null);
  const frame={frameId:'1',capturedAtUs:String(BigInt(clock.value)*1000n),clockQuality:'estimated',uncertaintyMs:15};
  await media.acceptPublisher(camera,{publisherId:randomUUID(),sequence:1,frame});
  const source=media.motionSourceEvidence(camera.deviceId);
  assert.deepEqual(source.context,camera);assert.deepEqual(source.frame,frame);assert.equal(source.sourceFresh,true);
  assert.equal(JSON.stringify(source).includes('private-publish-token'),false);
  assert.throws(()=>{source.context.connectionId=randomUUID();},TypeError);
  active=false;assert.equal(media.motionSourceEvidence(camera.deviceId),null);
});
