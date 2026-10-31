'use strict';
const {randomUUID}=require('node:crypto');
const {LeaseWatchdog}=require('./lease-watchdog');
const {validateJointTarget}=require('./motion-policy');
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
function validOperation(opcode,parameters){
  if(!parameters||typeof parameters!=='object'||Array.isArray(parameters))return false;
  const keys=Object.keys(parameters);
  if(['connect','disconnect','software_stop'].includes(opcode))return keys.length===0;
  if(opcode==='move_joint')return keys.every(key=>['joints','timeSec'].includes(key))&&Array.isArray(parameters.joints)&&parameters.joints.every(Number.isFinite)&&validateJointTarget(parameters.joints).ok&&(parameters.timeSec===undefined||Number.isFinite(parameters.timeSec)&&parameters.timeSec>=0.5&&parameters.timeSec<=30);
  if(opcode==='gripper')return keys.length===1&&keys[0]==='position'&&Number.isFinite(parameters.position)&&parameters.position>=0&&parameters.position<=1;
  if(opcode==='preset')return keys.length===1&&keys[0]==='name'&&['home','zero','observe'].includes(parameters.name);
  return false;
}
function createRobotControlPolicy({deviceId,getExecutionState,submit,onStopReceipt=()=>{},onLeaseChange=()=>true,onLeaseRevoke=()=>{},clock={now:()=>Date.now(),monotonic:()=>performance.now()}}){
  let context=null,hardware=null,lease=null,leaseTarget=null,leaseUpdate=null,leaseReady=false,previousStop=null,stopPromise=null,lastEpoch=0,lastSequence=-1,lastRenewal=-1,stopping=false,busy=false,stopResult=null,closed=false,closing=null;
  const reject=(code,commandId)=>({state:'rejected',code,...(commandId?{commandId}:{})});
  async function stop(reason,commandId=randomUUID(),actor){
    const requestActor=actor||{kind:'system',userId:null,trigger:reason};
    const coalesced=!!stopPromise;
    if(!stopPromise){
      const target=leaseTarget?{...leaseTarget}:null;
      lease=null;leaseReady=false;watchdog.clear();stopping=true;
      try{Promise.resolve(onLeaseRevoke(Object.freeze({...target,reason}))).catch(()=>{});}catch{/* SDK cancellation still proceeds if guard notification fails. */}
      stopPromise=Promise.resolve().then(async()=>{
        try{const result=await submit({purpose:'stop',opcode:'software_stop',parameters:{},commandId,reason,actor:requestActor,
          leaseId:target?.leaseId??null,leaseEpoch:target?.leaseEpoch??0});stopResult=result?.state==='stopped'?{...result,commandId}:{state:'unknown',code:'STOP_UNCONFIRMED',commandId};}
        catch{stopResult={state:'unknown',code:'STOP_UNCONFIRMED',commandId};}
        if(stopResult.state==='stopped'){
          stopping=false;
          const actual=getExecutionState();
          if(target&&target.executorEpoch===actual.executorEpoch&&target.hardwareFingerprint===actual.hardwareFingerprint)previousStop={...target,state:'stopped',stopCommandId:commandId,stoppedAt:clock.now()};
        }
        return stopResult;
      });
    }
    const operation=stopPromise;
    try{const result={...await operation,commandId};try{onStopReceipt({...result,actor:requestActor,coalesced});}catch{/* Receipt delivery cannot undo stopping. */}return result;}
    finally{if(stopPromise===operation)stopPromise=null;}
  }
  const watchdog=new LeaseWatchdog({monotonic:()=>clock.monotonic(),onExpire:event=>{
    if(lease&&event.binding?.leaseId===lease.leaseId&&event.binding.leaseEpoch===lease.leaseEpoch)return stop(event.reason||'lease_expired');
  }});
  function validContext(value){const actual=getExecutionState();return context&&actual.executorEpoch===context.executorEpoch&&actual.hardwareFingerprint===hardware&&BINDING.every(key=>value[key]===context[key]);}
  const api={deviceId,
    bind(value){
      if(closed||lease||stopping||stopPromise||leaseUpdate)throw Error('Previous execution must be stopped before rebinding');
      if(!value||value.deviceId!==deviceId||!BINDING.every(key=>typeof value[key]==='string'&&/^[a-f0-9-]{36}$/i.test(value[key]))||value.executorEpoch!==getExecutionState().executorEpoch)throw Error('Invalid executor binding');
      context=Object.freeze({...value});hardware=getExecutionState().hardwareFingerprint;return context;
    },
    currentLease(){return lease?Object.freeze({...lease}):null;},
    canBind(){return !closed&&!lease&&!stopping&&!stopPromise&&!leaseUpdate;},
    previousStopEvidence(){const actual=getExecutionState();return api.canBind()&&previousStop&&previousStop.executorEpoch===actual.executorEpoch&&previousStop.hardwareFingerprint===actual.hardwareFingerprint?Object.freeze({...previousStop}):null;},
    async revoke(reason='authorization_revoked'){return stop(reason);},
    close(){
      if(closing)return closing;
      closed=true;watchdog.close();
      closing=lease||leaseUpdate||busy||stopPromise?stop('robot_service_shutdown'):Promise.resolve();
      return closing;
    },
    async expire(){
      if(closed)return false;
      if(context&&(getExecutionState().executorEpoch!==context.executorEpoch||getExecutionState().hardwareFingerprint!==hardware)){
        context=null;if(lease)return stop('executor_changed');return false;
      }
      return watchdog.expire();
    },
    async handle(value){
      if(closed)return reject('POLICY_CLOSED',value?.commandId);
      await api.expire();
      if(closed)return reject('POLICY_CLOSED',value?.commandId);
      if(!value||!validContext(value))return reject('WRONG_EXECUTOR',value?.commandId);
      const receivedMono=clock.monotonic(),wall=clock.now();
      if(!Number.isSafeInteger(value.issuedAt)||!Number.isSafeInteger(value.expiresAt)||value.issuedAt>wall+500||value.expiresAt<=wall||value.expiresAt<=value.issuedAt||value.expiresAt-value.issuedAt>5000)return reject('EXPIRED_COMMAND',value.commandId);
      if(value.purpose==='stop'){
        if(value.opcode!=='software_stop'||!validOperation(value.opcode,value.parameters)||value.leaseId!==null||value.leaseEpoch!==0)return reject('INVALID_STOP',value.commandId);
        if(value.actor!==undefined&&(!value.actor||typeof value.actor!=='object'||Array.isArray(value.actor)||Object.keys(value.actor).length!==3||!['user','system'].includes(value.actor.kind)||typeof value.actor.trigger!=='string'||!/^[a-z_]{1,64}$/.test(value.actor.trigger)||(value.actor.kind==='user'?!/^[a-f0-9-]{36}$/i.test(value.actor.userId):value.actor.userId!==null)))return reject('INVALID_STOP_ACTOR',value.commandId);
        return stop(value.actor?.trigger||'operator_stop',value.commandId,value.actor);
      }
      if(stopping)return reject('STOP_UNCONFIRMED',value.commandId);
      if(value.purpose==='lease_grant'||value.purpose==='lease_renew'){
        if(leaseUpdate)return reject('LEASE_UPDATE_PENDING');
        if(!Number.isSafeInteger(value.leaseEpoch)||value.leaseEpoch<1||!Number.isSafeInteger(value.sequence)||value.sequence<0||typeof value.leaseId!=='string'||!/^[a-f0-9-]{36}$/i.test(value.leaseId)||value.expiresAt-wall>1000)return reject('INVALID_LEASE');
        const isGrant=value.purpose==='lease_grant';
        if(value.purpose==='lease_grant'){
          if(lease||value.leaseEpoch<=lastEpoch)return reject('LEASE_CONFLICT');
          lastEpoch=value.leaseEpoch;lastSequence=-1;lastRenewal=-1;
        }else if(!lease||lease.leaseId!==value.leaseId||lease.leaseEpoch!==value.leaseEpoch||value.sequence<=lastRenewal)return reject('STALE_LEASE');
        const target={...context,hardwareFingerprint:hardware,leaseId:value.leaseId,leaseEpoch:value.leaseEpoch};
        const update=Object.freeze({...target,sequence:value.sequence,issuedAt:value.issuedAt,expiresAt:value.expiresAt});
        const signedDeadline=receivedMono+Math.min(1000,value.expiresAt-wall);
        leaseTarget=target;
        try{
          if(isGrant)watchdog.reset(target);
          watchdog.renew(value.expiresAt-wall,{deadline:signedDeadline});
        }catch{
          await stop('lease_expired');return reject('LEASE_EXPIRED');
        }
        lastRenewal=value.sequence;lease={leaseId:value.leaseId,leaseEpoch:value.leaseEpoch};leaseTarget=target;
        leaseUpdate=update;leaseReady=false;
        try{
          const armed=await onLeaseChange(update,isGrant);
          if(armed!==true){if(lease?.leaseId===value.leaseId&&lease.leaseEpoch===value.leaseEpoch)await stop('local_guard_rejected');return reject('LOCAL_LEASE_GUARD_REJECTED');}
          const committedWall=clock.now(),committedMono=clock.monotonic();
          if(closed||!lease||lease.leaseId!==value.leaseId||lease.leaseEpoch!==value.leaseEpoch||stopping||!validContext(value)||committedMono>=signedDeadline||committedWall>=value.expiresAt){
            if(lease?.leaseId===value.leaseId&&lease.leaseEpoch===value.leaseEpoch)await stop('lease_expired');
            return reject('LEASE_EXPIRED');
          }
          leaseReady=true;return {state:'active',...lease};
        }catch{
          if(lease?.leaseId===value.leaseId&&lease.leaseEpoch===value.leaseEpoch)await stop('local_guard_rejected');
          return reject('LOCAL_LEASE_GUARD_REJECTED');
        }finally{if(leaseUpdate===update)leaseUpdate=null;}
      }
      if(value.purpose!=='command'||!validOperation(value.opcode,value.parameters)||value.opcode==='software_stop')return reject('UNSUPPORTED_OPERATION',value.commandId);
      if(typeof value.commandId!=='string'||!/^[a-f0-9-]{36}$/i.test(value.commandId))return reject('INVALID_COMMAND_ID');
      if(!lease||value.leaseId!==lease.leaseId||value.leaseEpoch!==lease.leaseEpoch)return reject('LEASE_REQUIRED',value.commandId);
      if(!leaseReady)return reject('LEASE_NOT_READY',value.commandId);
      if(!Number.isSafeInteger(value.sequence)||value.sequence<=lastSequence)return reject('SEQUENCE_REPLAYED',value.commandId);
      if(!['connect','disconnect'].includes(value.opcode)&&(!Number.isFinite(getExecutionState().freshAt)||wall-getExecutionState().freshAt>500||wall-getExecutionState().freshAt< -50))return reject('ROBOT_STATE_STALE',value.commandId);
      if(value.opcode==='disconnect'){lastSequence=value.sequence;return stop('sdk_disconnect',value.commandId);}
      if(busy)return reject('ROBOT_BUSY',value.commandId);
      lastSequence=value.sequence;busy=true;
      try{return await submit(value);}catch{return {commandId:value.commandId,state:'unknown',code:'SUBMISSION_RESULT_UNKNOWN'};}finally{busy=false;}
    }
  };
  return api;
}
module.exports={createRobotControlPolicy,validOperation};
