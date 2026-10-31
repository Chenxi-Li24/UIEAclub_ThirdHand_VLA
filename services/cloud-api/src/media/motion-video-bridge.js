'use strict';
// A source-health attestation, never a command or a grant of operator control.
// bindings is a trusted commissioning repository, not request-supplied JSON.
const {UUID}=require('../../../device-relay/src/protocol');
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const fail=code=>Object.assign(Error(code),{code});
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const reference=value=>typeof value==='string'&&value.length>0&&value.length<=256&&!/[\x00-\x20\x7f]/.test(value);
const same=(left,right)=>object(left)&&object(right)&&BINDING.every(key=>left[key]===right[key]);
function validContext(context,camera=false){
  return object(context)&&BINDING.every(key=>camera&&key==='executorEpoch'&&context[key]===null||UUID.test(context[key]||''));
}
function validFrame(frame,now){
  if(!object(frame)||typeof frame.frameId!=='string'||!/^\d{1,19}$/.test(frame.frameId)
    ||typeof frame.capturedAtUs!=='string'||!/^\d{1,19}$/.test(frame.capturedAtUs)
    ||!['synchronized','estimated'].includes(frame.clockQuality)
    ||!Number.isFinite(frame.uncertaintyMs)||frame.uncertaintyMs<0||frame.uncertaintyMs>500)return false;
  const age=Number(BigInt(now)*1000n-BigInt(frame.capturedAtUs))/1000;
  return age>=-frame.uncertaintyMs&&age+frame.uncertaintyMs<=500;
}
function createMotionVideoBridge({mediaService,devices,bindings,signer,clock={now:()=>Date.now()}}){
  if(typeof mediaService?.motionSourceEvidence!=='function'||typeof bindings?.getVerifiedBinding!=='function'
    ||typeof devices?.get!=='function'||typeof signer?.sign!=='function')throw fail('MOTION_VIDEO_CONFIGURATION_REQUIRED');
  const sequences=new Map();
  return {async issue({robotContext,cameraContext}={}){
    if(!validContext(robotContext)||!validContext(cameraContext,true))throw fail('INVALID_MOTION_VIDEO_CONTEXT');
    // An asynchronous lookup must not freeze the source state or its age before
    // a possible revocation. Read both after it has completed.
    const binding=await bindings.getVerifiedBinding({robotDeviceId:robotContext.deviceId,cameraDeviceId:cameraContext.deviceId});
    const now=Number(clock.now());
    if(!Number.isSafeInteger(now)||now<0)throw fail('MOTION_VIDEO_UNAVAILABLE');
    if(!same(devices.get(robotContext.deviceId),robotContext))throw fail('MOTION_ROBOT_CONTEXT_CHANGED');
    if(!object(binding)||binding.state!=='verified'||!UUID.test(binding.id||'')
      ||binding.robotDeviceId!==robotContext.deviceId||binding.cameraDeviceId!==cameraContext.deviceId
      ||!reference(binding.evidenceId)||!Number.isSafeInteger(binding.expiresAt)||now>=binding.expiresAt)
      throw fail('MOTION_CAMERA_BINDING_REQUIRED');
    const source=mediaService.motionSourceEvidence(cameraContext.deviceId);
    if(!source||!same(source.context,cameraContext)||source.sourceFresh!==true||!validFrame(source.frame,now))
      throw fail('MOTION_VIDEO_UNAVAILABLE');
    const key=robotContext.deviceId;
    if(!sequences.has(key)&&sequences.size>=64)throw fail('MOTION_VIDEO_CAPACITY');
    const sequence=(sequences.get(key)||0)+1;
    if(!Number.isSafeInteger(sequence))throw fail('MOTION_VIDEO_CAPACITY');
    sequences.set(key,sequence);
    return signer.sign({schema:1,purpose:'motion_video_health',
      ...Object.fromEntries(BINDING.map(name=>[name,robotContext[name]])),
      cameraBindingId:binding.id,cameraContext:Object.fromEntries(BINDING.map(name=>[name,cameraContext[name]])),
      sequence,sourceFresh:true,frame:{frameId:source.frame.frameId,capturedAtUs:source.frame.capturedAtUs,
        clockQuality:source.frame.clockQuality,uncertaintyMs:source.frame.uncertaintyMs},
      issuedAt:now,expiresAt:Math.min(now+950,binding.expiresAt)});
  }};
}
module.exports={createMotionVideoBridge};
