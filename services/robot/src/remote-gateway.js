'use strict';
// Private local ingress. Every real command still carries the cloud signature;
// possession of the edge transport token alone cannot authorize motion.
const {randomUUID,createHash}=require('node:crypto');
const {tokenMatches}=require('./execution-token');
const {createRobotControlPolicy}=require('./control-policy');
const {createSoftwareStopAdapter}=require('./software-stop-adapter');
const {verifyEnvelope}=require('../../device-relay/src/envelope');
const {UUID}=require('../../device-relay/src/protocol');

function createRemoteRobotGateway({controller,deviceId,token,signingKeys,readOnly=false,clock={now:()=>Date.now(),monotonic:()=>performance.now()},hardwareAccepted=()=>false,initialStopVerified=()=>false,getStopEvidence=()=>null,stopProfile=null,requestControlledStop=null,nativeStopSupported=false,requireWorkerLeaseGuard=controller?.config?.remoteLeaseGuard===true,stopTimeoutMs=3000}){
  if(!UUID.test(deviceId)||!token||!(signingKeys instanceof Map)||!signingKeys.size)throw Error('Remote device identity, local token and cloud public keys required');
  let executorEpoch=randomUUID(),bound=null,closed=false,closing=null,ticking=false,sourceSequence=0,activeSourceCommand=null,captureHealth=null,mediaHealth=null;
  const sources=new Set(),sourceTimers=new Map(),ordinaryPending=new Map(),sourceTimes=new Map();
  const hardwareFingerprint=()=>createHash('sha256').update(JSON.stringify({pid:controller.bridge?.child?.pid??null,config:controller.config})).digest('hex');
  const baselineFingerprint=controller.config.simulate===true||initialStopVerified()===true?hardwareFingerprint():null;
  const bindingAccepted=()=>readOnly===true||controller.config.simulate===true||hardwareAccepted()===true&&baselineFingerprint===hardwareFingerprint();
  const getExecutionState=()=>({executorEpoch,hardwareFingerprint:hardwareFingerprint(),freshAt:controller.stateReady?controller.latestRobotStateAtMs:null});
  const recordingHealthy=()=>!!bound&&sources.size>0&&captureHealth?.bootId===bound.bootId&&captureHealth.executorEpoch===executorEpoch&&captureHealth.writable&&clock.monotonic()-captureHealth.receivedAt<2000&&(captureHealth.sourceSequence===sourceSequence||sourceTimes.has(captureHealth.sourceSequence+1)&&clock.monotonic()-sourceTimes.get(captureHealth.sourceSequence+1)<1000);
  const videoHealthy=()=>{
    if(!bound||!mediaHealth||mediaHealth.bootId!==bound.bootId||mediaHealth.executorEpoch!==executorEpoch||mediaHealth.connectionId!==bound.connectionId||mediaHealth.certificateId!==bound.certificateId||!mediaHealth.sourceFresh||clock.monotonic()>=mediaHealth.deadline||clock.monotonic()-mediaHealth.frameReceivedAt>=500||!mediaHealth.frame)return false;
    const age=Number(BigInt(clock.now())*1000n-BigInt(mediaHealth.frame.capturedAtUs))/1000;
    return mediaHealth.frame.clockQuality!=='unreliable'&&age>=-mediaHealth.frame.uncertaintyMs&&age+mediaHealth.frame.uncertaintyMs<=500;
  };
  const accepted=()=>readOnly===true?recordingHealthy():controller.config.simulate===true||bindingAccepted()&&stopAdapter.capabilities().controlledStop&&recordingHealthy()&&videoHealthy();
  let preparedBootId=null,priorPreparedStop=null;
  let knownStopped=baselineFingerprint!==null&&controller.bridge?.connected!==true?{executorEpoch,hardwareFingerprint:hardwareFingerprint()}:null;
  function submitController(value,{emitOutcome=true}={}){
    const stop=value.opcode==='software_stop';
    const submittedEpoch=executorEpoch,submittedHardware=hardwareFingerprint();
    if(!stop)activeSourceCommand=value.commandId;
    // Read-only lease expiry releases the SDK connection, never claims a
    // physical stop or emits a motion/stop motor command.
    const command={cmd:readOnly&&stop?'disconnect':value.opcode,request_id:value.commandId};
    const p=value.parameters||{};
    if(value.opcode==='move_joint'){command.joints_deg=p.joints;if(p.timeSec!==undefined)command.time_sec=p.timeSec;}
    else if(value.opcode==='gripper')command.position=p.position;
    else if(value.opcode==='preset')command.name=p.name;
    return new Promise(resolve=>{
      let settled=false;
      const finish=(state,code,details={})=>{
        if(settled)return;settled=true;clearTimeout(timer);controller.off('message',onMessage);ordinaryPending.delete(value.commandId);
        if(stop&&state==='unknown'&&!code)code='STOP_UNCONFIRMED';
        if(stop){
          if(state==='stopped'&&executorEpoch===submittedEpoch&&hardwareFingerprint()===submittedHardware)knownStopped={executorEpoch,hardwareFingerprint:submittedHardware};
          for(const pending of [...ordinaryPending.values()])pending(state==='stopped'?'stopped':'unknown',state==='stopped'?'PRIORITY_STOP':'STOP_UNCONFIRMED');
        }
        if(emitOutcome)controller.emit('message',{type:'remote_command_outcome',commandId:value.commandId,opcode:value.opcode,state,actor:value.actor||null,trigger:value.reason||null,ts:clock.now(),...(code?{code}:{}),...details});
        if(activeSourceCommand===value.commandId)activeSourceCommand=null;resolve({commandId:value.commandId,state,...(code?{code}:{}),...details});
      };
      const onMessage=message=>{
        if(readOnly&&stop&&message.type==='connection'&&message.connected===false){
          if(message.request_id!==value.commandId)return;
          return message.sdk_released===true?finish('stopped','READ_ONLY_SDK_DISCONNECTED'):finish('unknown','SDK_RELEASE_UNCONFIRMED');
        }
        if(stop&&!readOnly&&controller.config.simulate!==true&&message.type==='connection'&&message.connected===false&&message.request_id===value.commandId){
          return finish('unknown',message.sdk_released===true?'SDK_RELEASED_PHYSICAL_STOP_UNKNOWN':'SDK_RELEASE_UNCONFIRMED',{sdkReleased:message.sdk_released===true});
        }
        if(['connect','disconnect'].includes(value.opcode)&&message.type==='connection'&&message.connected===(value.opcode==='connect'))return finish('completed');
        if(message.request_id!==value.commandId)return;
        if(message.type==='error')return finish('failed','ROBOT_REJECTED');
        if(message.type==='command_status'&&message.status==='complete'){
          if(!stop)return finish(message.reached===false?'failed':'completed');
          if(controller.config.simulate===true)return finish(message.stopped===true?'stopped':'unknown');
          return finish('unknown','STOP_UNCONFIRMED');
        }
      };
      const timer=setTimeout(()=>finish('unknown',stop?'STOP_UNCONFIRMED':'SUBMISSION_RESULT_UNKNOWN'),stop?stopTimeoutMs:35000);timer.unref();
      controller.on('message',onMessage);
      if(!stop)ordinaryPending.set(value.commandId,finish);
      // A disconnected flag is also false while SDK construction is pending.
      // Always queue disconnect and wait for its connection:false receipt; the
      // Python command queue processes it after any in-flight initialization.
      if(stop&&knownStopped?.executorEpoch===executorEpoch&&knownStopped.hardwareFingerprint===submittedHardware){finish('stopped','ALREADY_STOPPED');return;}
      if(value.opcode==='connect'&&controller.bridge?.connected===true){finish('completed','ALREADY_CONNECTED');return;}
      knownStopped=null;if(!stop)priorPreparedStop=null;
      try{controller.handleCommand(command,message=>{if(message.type==='error')finish('rejected','ROBOT_REJECTED');},'remote-gateway',false);}catch{finish('unknown','SUBMISSION_RESULT_UNKNOWN');}
    });
  }
  const stopAdapter=createSoftwareStopAdapter({getExecutionState,clock,stopProfile,requestControlledStop,nativeStopSupported,
    timeoutMs:Math.min(1000,stopTimeoutMs),readStopEvidence:operation=>getStopEvidence({...operation,now:clock.now()}),
    releaseSdk:operation=>submitController({purpose:'stop',opcode:'software_stop',parameters:{},commandId:operation.commandId,reason:operation.reason,actor:operation.actor},{emitOutcome:false})});
  async function submit(value){
    if(value.opcode!=='software_stop'||readOnly||controller.config.simulate===true)return submitController(value);
    const epoch=executorEpoch,fingerprint=hardwareFingerprint();
    const result=await stopAdapter.stop({commandId:value.commandId,executorEpoch:epoch,hardwareFingerprint:fingerprint,
      leaseId:value.leaseId??null,leaseEpoch:value.leaseEpoch??0,reason:value.reason,actor:value.actor});
    if(result.state==='stopped'&&executorEpoch===epoch&&hardwareFingerprint()===fingerprint)knownStopped={executorEpoch:epoch,hardwareFingerprint:fingerprint};
    for(const pending of [...ordinaryPending.values()])pending(result.state==='stopped'?'stopped':'unknown',result.state==='stopped'?'PRIORITY_STOP':'STOP_UNCONFIRMED');
    controller.emit('message',{type:'remote_command_outcome',opcode:'software_stop',...result,actor:value.actor||null,trigger:value.reason||null,ts:clock.now()});
    return result;
  }
  const policy=createRobotControlPolicy({deviceId,getExecutionState,submit,clock,
    onLeaseChange:(lease,isGrant)=>{
      if(!requireWorkerLeaseGuard)return true;
      const method=controller.bridge?.[isGrant?'armRemoteLease':'renewRemoteLease'];
      return typeof method==='function'&&method.call(controller.bridge,lease)===true;
    },onLeaseRevoke:({reason})=>{if(requireWorkerLeaseGuard)controller.bridge?.revokeRemoteLease?.(reason);},
    onStopReceipt:receipt=>controller.emit('message',{type:'remote_stop_receipt',...receipt,ts:clock.now()})});
  function removeSource(response){sources.delete(response);clearInterval(sourceTimers.get(response));sourceTimers.delete(response);if(!closed&&!sources.size&&policy.currentLease())void policy.revoke('capture_disconnected');}
  function sourceWrite(response,event,value){if(response.destroyed||response.writableEnded)return;const writable=response.write(`event: ${event}\ndata: ${JSON.stringify(value)}\n\n`);if(!writable){removeSource(response);response.end();}}
  const publish=message=>{
    if(!['robot_state','connection','command_status','software_stop','error','remote_command_outcome','remote_stop_receipt','remote_lease_status','remote_lease_expired'].includes(message?.type))return;
    const value={type:'robot_event',sequence:++sourceSequence,receivedAt:new Date(clock.now()).toISOString(),executorEpoch,sourceMode:controller.config.simulate?'simulation':controller.config.dryRun?'dry-run':'hardware',hardwareFingerprint:hardwareFingerprint(),commandId:activeSourceCommand,message};
    sourceTimes.set(sourceSequence,clock.monotonic());if(sourceTimes.size>4096)sourceTimes.delete(sourceTimes.keys().next().value);
    for(const response of sources)sourceWrite(response,'robot_event',value);
  };
  controller.on('message',publish);
  const sourceSnapshot=()=>{for(const response of sources)sourceWrite(response,'source_snapshot',{type:'source_snapshot',sequence:sourceSequence,executorEpoch,receivedAt:new Date(clock.now()).toISOString()});};
  const rotated=()=>{executorEpoch=randomUUID();knownStopped=null;priorPreparedStop=null;sourceSnapshot();void policy.expire().catch(()=>{});};
  controller.bridge?.on('bridge_ready',rotated);
  const disconnected=message=>{if(message.type==='connection'&&String(message.reason||'').startsWith('bridge_exit:'))rotated();};
  controller.on('message',disconnected);
  const interval=setInterval(async()=>{if(ticking||closed)return;ticking=true;try{if(controller.config.simulate!==true&&policy.currentLease()&&!accepted())await policy.revoke('capture_or_acceptance_lost');else await policy.expire();}finally{ticking=false;}},50);interval.unref();
  const json=(response,status,value)=>{response.writeHead(status,{'content-type':'application/json','cache-control':'no-store'});response.end(JSON.stringify(value));};
  return {policy,
    async handle(request,response){
      const path=new URL(request.url,'http://localhost').pathname;if(!path.startsWith('/edge-control/v1/'))return false;
      if(closed){json(response,503,{error:'GATEWAY_CLOSED'});return true;}
      if(!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(request.socket.remoteAddress)||request.headers.origin||request.headers.cookie||!tokenMatches(token,request.headers['x-thirdhand-edge-token'])){json(response,403,{error:'EDGE_AUTH_REQUIRED'});return true;}
      try{
        if(request.method==='GET'&&path==='/edge-control/v1/context'){
          json(response,200,{deviceId,executorEpoch,hardwareFingerprint:hardwareFingerprint(),sdkConnected:controller.bridge?.connected===true,bindingAccepted:bindingAccepted(),controlAccepted:accepted(),readOnly,recordingHealthy:recordingHealthy(),videoHealthy:videoHealthy(),sourceSequence,stopCapabilities:stopAdapter.capabilities(),workerLeaseGuardRequired:requireWorkerLeaseGuard});return true;
        }
        if(request.method==='GET'&&path==='/edge-control/v1/events'){
          if(sources.size>=2){json(response,429,{error:'SOURCE_SUBSCRIBER_LIMIT'});return true;}
          response.writeHead(200,{'content-type':'text/event-stream','cache-control':'no-store','x-accel-buffering':'no'});
          sources.add(response);response.on('close',()=>removeSource(response));
          sourceWrite(response,'source_snapshot',{type:'source_snapshot',sequence:sourceSequence,executorEpoch,receivedAt:new Date(clock.now()).toISOString()});
          if(!sources.has(response)||response.destroyed)return true;
          const keepalive=setInterval(()=>sourceWrite(response,'source_heartbeat',{type:'source_heartbeat',sequence:sourceSequence,receivedAt:new Date(clock.now()).toISOString()}),500);keepalive.unref();sourceTimers.set(response,keepalive);return true;
        }
        if(request.method!=='POST'){json(response,405,{error:'METHOD_NOT_ALLOWED'});return true;}
        if(!/^application\/json(?:\s*;.*)?$/i.test(request.headers['content-type']||''))throw Error('INVALID_REQUEST');
        const chunks=[];let length=0;for await(const chunk of request){length+=chunk.length;if(length>32768)throw Error('BODY_TOO_LARGE');chunks.push(chunk);}
        if(closed){json(response,503,{error:'GATEWAY_CLOSED'});return true;}
        const value=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(path==='/edge-control/v1/prepare-binding'){
          if(!value||Array.isArray(value)||Object.keys(value).length!==1||!UUID.test(value.bootId))throw Error('INVALID_BINDING');
          if(!policy.canBind()){json(response,409,{error:'BINDING_NOT_STOPPED'});return true;}
          const previous=policy.previousStopEvidence();
          if(previous)priorPreparedStop=previous;
          if(preparedBootId&&preparedBootId!==value.bootId){executorEpoch=randomUUID();await policy.expire();if(closed){json(response,503,{error:'GATEWAY_CLOSED'});return true;}sourceSnapshot();if(knownStopped)knownStopped={executorEpoch,hardwareFingerprint:hardwareFingerprint()};}
          preparedBootId=value.bootId;
          json(response,200,{deviceId,executorEpoch,hardwareFingerprint:hardwareFingerprint(),sdkConnected:controller.bridge?.connected===true,bindingAccepted:bindingAccepted(),controlAccepted:accepted()});return true;
        }
        if(path==='/edge-control/v1/capture-health'){
          if(!value||Array.isArray(value)||Object.keys(value).length!==4||!UUID.test(value.bootId)||value.executorEpoch!==executorEpoch||typeof value.writable!=='boolean'||!Number.isSafeInteger(value.sourceSequence)||value.sourceSequence<0||value.sourceSequence>sourceSequence)throw Error('INVALID_CAPTURE_HEALTH');
          captureHealth={...value,receivedAt:clock.monotonic()};json(response,200,{recorded:true});return true;
        }
        if(path==='/edge-control/v1/media-health'){
          const payload=verifyEnvelope(value,signingKeys,bound,clock.now()),frame=payload.frame;
          if(payload.purpose!=='media_publish'||!UUID.test(payload.publisherId)||!Number.isSafeInteger(payload.sequence)||payload.sequence<1||payload.expiresAt-payload.issuedAt>1000||typeof payload.sourceFresh!=='boolean'||frame!==null&&(!frame||typeof frame!=='object'||Array.isArray(frame)||Object.keys(frame).length!==4||!['frameId','capturedAtUs','clockQuality','uncertaintyMs'].every(key=>Object.hasOwn(frame,key))||typeof frame.frameId!=='string'||!/^\d{1,19}$/.test(frame.frameId)||typeof frame.capturedAtUs!=='string'||!/^\d{1,19}$/.test(frame.capturedAtUs)||!['synchronized','estimated','unreliable'].includes(frame.clockQuality)||!Number.isFinite(frame.uncertaintyMs)||frame.uncertaintyMs<0||frame.uncertaintyMs>60000))throw Error('INVALID_MEDIA_HEALTH');
          const same=mediaHealth?.publisherId===payload.publisherId&&mediaHealth.connectionId===payload.connectionId;
          if(same&&(payload.sequence<=mediaHealth.sequence||frame&&mediaHealth.frame&&BigInt(frame.frameId)<BigInt(mediaHealth.frame.frameId)))throw Error('STALE_MEDIA_HEALTH');
          const repeated=same&&frame&&mediaHealth.frame&&frame.frameId===mediaHealth.frame.frameId;
          if(repeated&&frame.capturedAtUs!==mediaHealth.frame.capturedAtUs)throw Error('CONFLICTING_MEDIA_FRAME');
          mediaHealth={bootId:payload.bootId,executorEpoch:payload.executorEpoch,connectionId:payload.connectionId,certificateId:payload.certificateId,publisherId:payload.publisherId,sequence:payload.sequence,sourceFresh:payload.sourceFresh,frame,deadline:clock.monotonic()+Math.min(950,payload.expiresAt-clock.now()),frameReceivedAt:repeated?mediaHealth.frameReceivedAt:clock.monotonic()};json(response,200,{recorded:true});return true;
        }
        if(path==='/edge-control/v1/bind'){
          if(!value||Array.isArray(value)||Object.keys(value).length!==5||!['deviceId','bootId','executorEpoch','connectionId','certificateId'].every(key=>UUID.test(value[key])))throw Error('INVALID_BINDING');
          if(preparedBootId&&value.bootId!==preparedBootId)throw Error('BINDING_NOT_PREPARED');
          preparedBootId=value.bootId;bound=policy.bind(value);mediaHealth=null;json(response,200,{bound:true,context:bound,previousStop:policy.previousStopEvidence()||priorPreparedStop,controlAuthorized:false});return true;
        }
        if(path==='/edge-control/v1/envelope'){
          const payload=verifyEnvelope(value,signingKeys,bound,clock.now());
          if(readOnly&&payload.purpose==='command'&&!['connect','disconnect'].includes(payload.opcode)){json(response,403,{state:'rejected',code:'READ_ONLY_DEVICE',commandId:payload.commandId});return true;}
          if(!accepted()&&payload.purpose!=='stop'){json(response,409,{state:'rejected',code:'HARDWARE_ACCEPTANCE_REQUIRED',commandId:payload.commandId});return true;}
          const result=await policy.handle(payload);
          json(response,closed?503:200,closed?{error:'GATEWAY_CLOSED'}:result);return true;
        }
        json(response,404,{error:'NOT_FOUND'});return true;
      }catch{json(response,403,{error:'REMOTE_REQUEST_REJECTED'});return true;}
    },
    close(){
      if(closing)return closing;
      closed=true;clearInterval(interval);controller.bridge?.off('bridge_ready',rotated);controller.off('message',disconnected);
      closing=Promise.resolve(policy.close()).finally(()=>{controller.off('message',publish);for(const response of sources){clearInterval(sourceTimers.get(response));response.end();}sources.clear();sourceTimers.clear();});
      return closing;
    }
  };
}
module.exports={createRemoteRobotGateway};
