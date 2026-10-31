'use strict';
const {randomUUID,randomBytes,createHash}=require('node:crypto');
const {authorize}=require('../../../../platform/identity/src/policy');
const {validOperation}=require('../../../robot/src/control-policy');
const fail=code=>Object.assign(Error(code),{code});
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const same=(left,right)=>left&&right&&BINDING.every(key=>left[key]===right[key]);
const hash=value=>createHash('sha256').update(value).digest('hex');
function createControlService({repository,sessions,channels,devices,signer,clock={now:()=>new Date(),monotonic:()=>performance.now()},readiness=async()=>false}){
  const holders=new Map(),pending=new Set(),revocations=new Map();let closed=false;
  function track(promise){pending.add(promise);promise.catch(()=>{}).finally(()=>pending.delete(promise));return promise;}
  async function actor(principal,action,binding){if(!authorize(principal,action).ok)throw fail('FORBIDDEN');await repository.validatePrincipal(principal);if(binding)channels.requireFresh(principal,binding);}
  function context(deviceId){const value=devices.get(deviceId);if(!value||!value.executorEpoch||value.controlAccepted!==true)throw fail('DEVICE_UNAVAILABLE');return Object.fromEntries(BINDING.map(key=>[key,value[key]]));}
  function leaseContext(lease){return {deviceId:lease.deviceId,bootId:lease.bootId,executorEpoch:lease.executorEpoch,connectionId:lease.deviceConnectionId,certificateId:lease.certificateId};}
  function signed(purpose,binding,value,ttl=1000){const now=clock.now().getTime();return signer.sign({schema:1,purpose,...binding,...value,issuedAt:now,expiresAt:now+ttl});}
  async function stopDevice(binding,reason,actorUserId=null){
    const commandId=randomUUID();
    try{if(!same(context(binding.deviceId),binding))return {state:'unknown',code:'DEVICE_CONTEXT_CHANGED',commandId};
      const response=await devices.request(binding.deviceId,signed('stop',binding,{commandId,leaseId:null,leaseEpoch:0,sequence:0,opcode:'software_stop',parameters:{},actor:{kind:actorUserId?'user':'system',userId:actorUserId,trigger:reason}}));
      return response?.state==='stopped'&&response.commandId===commandId?{state:'stopped',commandId}:{state:'unknown',code:'STOP_UNCONFIRMED',commandId};
    }catch{return {state:'unknown',code:'STOP_UNCONFIRMED',commandId};}
  }
  async function revoke(lease,reason,actorUserId=null){
    if(revocations.has(lease.id))return revocations.get(lease.id);
    holders.delete(lease.id);
    channels.close(lease.connectionId);
    const operation=(async()=>{
      // Dispatch stop before attempting any persistence. Write failure must not
      // delay an already authenticated priority stop or create a new grant.
      const stopping=stopDevice(leaseContext(lease),reason,actorUserId);
      await repository.markRevoking(lease.id,reason).catch(()=>{});
      const result=await stopping;
      if(result.state==='stopped')await repository.completeStop(lease.id,reason).catch(()=>{});
      return result;
    })();
    revocations.set(lease.id,operation);try{return await operation;}finally{revocations.delete(lease.id);}
  }
  async function grant(principal,lease,browser,binding){
    try{
      const result=await devices.request(lease.deviceId,signed('lease_grant',binding,{leaseId:lease.id,leaseEpoch:lease.leaseEpoch,sequence:0}));
      if(result?.state!=='active'||result.leaseId!==lease.id||result.leaseEpoch!==lease.leaseEpoch)throw fail('LEASE_UNCONFIRMED');
      await actor(principal,'control.request',browser);
      if(!same(context(lease.deviceId),binding)||!await readiness(principal,lease.deviceId))throw fail('DEVICE_UNAVAILABLE');
      const active=await repository.confirm(principal,lease.id);holders.set(active.id,{lease:active,principal,browser});return active;
    }catch(error){await revoke(lease,'grant_failed');throw error;}
  }
  const api={
    async listDevices(principal){if(!authorize(principal,'telemetry.read').ok)throw fail('FORBIDDEN');const rows=await repository.listDevices();return rows.map(row=>({...row,online:!!devices.get(row.id),controlAccepted:devices.get(row.id)?.controlAccepted===true,readOnly:devices.get(row.id)?.readOnly===true}));},
    async status(principal,deviceId){await actor(principal,'control.request');const lease=await repository.current(deviceId);return {deviceId,online:!!devices.get(deviceId),controlAccepted:devices.get(deviceId)?.controlAccepted===true,lease:lease?{leaseEpoch:lease.leaseEpoch,state:lease.state,own:lease.sessionId===principal.sessionId}:null};},
    async requestLease(principal,input){
      await actor(principal,'control.request',input);const binding=context(input.deviceId);
      if(!await readiness(principal,input.deviceId))throw fail('CONTROL_READINESS_REQUIRED');
      const lease=await repository.reserve(principal,{context:binding,clientInstanceId:input.clientInstanceId,connectionId:input.connectionId});
      return grant(principal,lease,input,binding);
    },
    async renewFromBrowser(principal,input){
      if(!authorize(principal,'control.command').ok)throw fail('FORBIDDEN');channels.requireFresh(principal,input);
      const holder=[...holders.values()].find(value=>value.lease.deviceId===input.deviceId&&value.lease.sessionId===principal.sessionId&&value.browser.connectionId===input.connectionId&&value.browser.clientInstanceId===input.clientInstanceId);
      if(!holder)throw fail('LEASE_REQUIRED');
      if(holder.renewal)return holder.renewal;
      holder.renewal=(async()=>{
        await actor(principal,'control.command',input);
        const binding=context(input.deviceId);
        if(!same(binding,leaseContext(holder.lease))||!await readiness(principal,input.deviceId)){await revoke(holder.lease,'readiness_lost');throw fail('DEVICE_UNAVAILABLE');}
        const renewed=await repository.renew(principal,holder.lease.id);
        const result=await devices.request(input.deviceId,signed('lease_renew',binding,{leaseId:renewed.id,leaseEpoch:renewed.leaseEpoch,sequence:renewed.renewalSequence}));
        if(result?.state!=='active'||result.leaseId!==renewed.id||result.leaseEpoch!==renewed.leaseEpoch){await revoke(renewed,'renewal_unconfirmed');throw fail('LEASE_UNCONFIRMED');}
        holder.lease=renewed;return {renewed:true};
      })();
      try{return await holder.renewal;}finally{holder.renewal=null;}
    },
    async requestTakeover(principal,input){
      await actor(principal,'control.request',input);context(input.deviceId);
      if(!Number.isSafeInteger(input.targetEpoch)||input.targetEpoch<1)throw fail('INVALID_INPUT');
      const nonce=randomBytes(32).toString('base64url'),request=await repository.requestTakeover(principal,{...input,nonceHash:hash(nonce)});
      return {...request,nonce,requiresConfirmation:true};
    },
    async confirmTakeover(principal,input){
      await actor(principal,'control.request',input);
      if(typeof input.nonce!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(input.nonce))throw fail('TAKEOVER_INVALID');
      const old=await repository.beginTakeover(principal,{...input,nonceHash:hash(input.nonce)});
      holders.delete(old.id);channels.close(old.connectionId);let stopped=false,next=null;
      try{
        const binding=leaseContext(old),result=await stopDevice(binding,'takeover',principal.userId);
        if(result.state!=='stopped')throw fail('STOP_UNCONFIRMED');stopped=true;
        await actor(principal,'control.request',input);
        if(!same(context(old.deviceId),binding)||!await readiness(principal,old.deviceId))throw fail('DEVICE_UNAVAILABLE');
        next=await repository.finishTakeover(principal,{requestId:input.requestId,oldLease:old,context:binding,clientInstanceId:input.clientInstanceId,connectionId:input.connectionId});
        const active=await grant(principal,next,input,binding);
        await repository.completeTakeover(input.requestId,active.id);return active;
      }catch(error){if(next)await revoke(next,'takeover_grant_failed');if(stopped)await repository.completeStop(old.id,'takeover_not_granted').catch(()=>{});await repository.failTakeover(input.requestId,error.code||'TAKEOVER_FAILED').catch(()=>{});throw error;}
    },
    async dispatchRealCommand(principal,input){
      await actor(principal,'control.command',input);const binding=context(input.deviceId);
      if(!await readiness(principal,input.deviceId))throw fail('CONTROL_READINESS_REQUIRED');
      if(typeof input.commandId!=='string'||!/^[a-f0-9-]{36}$/i.test(input.commandId)||!validOperation(input.opcode,input.parameters)||input.opcode==='software_stop')throw fail('INVALID_INPUT');
      if(devices.get(input.deviceId)?.readOnly===true&&!['connect','disconnect'].includes(input.opcode))throw fail('READ_ONLY_DEVICE');
      const lease=await repository.find(input.leaseId);
      if(!lease||lease.deviceId!==input.deviceId||!same(binding,leaseContext(lease)))throw fail('FORBIDDEN');
      const expiresAt=new Date(clock.now().getTime()+1000),record=await repository.recordCommand(principal,{...input,expiresAt});
      if(!record.fresh)return record.receipt;
      let result={commandId:input.commandId,state:'unknown',code:'SUBMISSION_RESULT_UNKNOWN'};
      try{
        // Check the same browser again after the durable DB operation. An old
        // request must not be delivered after a slow commit or connection swap.
        channels.requireFresh(principal,input);
        if(!same(context(input.deviceId),binding))throw fail('DEVICE_UNAVAILABLE');
        const received=await devices.request(input.deviceId,signer.sign({schema:1,purpose:'command',...binding,commandId:input.commandId,leaseId:lease.id,leaseEpoch:lease.leaseEpoch,sequence:record.sequence,opcode:input.opcode,parameters:input.parameters,issuedAt:expiresAt.getTime()-1000,expiresAt:expiresAt.getTime()}));
        if(received?.commandId===input.commandId&&['accepted','started','completed','stopped','rejected','failed','unknown'].includes(received.state))result={commandId:input.commandId,state:received.state,...(typeof received.code==='string'&&/^[A-Z0-9_]{1,80}$/.test(received.code)?{code:received.code}:{})};
      }catch{/* A lost command acknowledgement is never automatically retried. */}
      await repository.finishCommand(record.receipt,result).catch(()=>{});
      if(result.state==='unknown')await revoke(lease,'command_result_unknown');
      if(input.opcode==='disconnect'&&result.state==='stopped'){holders.delete(lease.id);channels.close(lease.connectionId);await repository.completeStop(lease.id,'sdk_disconnected').catch(()=>{});}
      return {...record.receipt,...result};
    },
    async stop(principal,{deviceId,...browser}){
      await actor(principal,'control.stop',browser);
      const lease=await repository.current(deviceId);
      return lease?revoke(lease,'operator_stop',principal.userId):stopDevice(context(deviceId),'operator_stop',principal.userId);
    },
    async drain(){while(pending.size)await Promise.allSettled([...pending]);},
    async close(){closed=true;clearInterval(timer);sessions.events.off('revoked',revoked);sessions.events.off('unavailable',unavailable);channels.events.off('fresh',fresh);channels.events.off('closed',disconnected);devices.events?.off('disconnected',deviceDisconnected);await Promise.allSettled([...holders.values()].map(value=>revoke(value.lease,'cloud_service_shutdown')));await api.drain();}
  };
  function fresh({principal,binding}){for(const holder of holders.values())if(holder.browser.connectionId===binding.connectionId)track(api.renewFromBrowser(principal,{...binding,deviceId:holder.lease.deviceId}).catch(()=>revoke(holder.lease,'renewal_failed')));}
  function disconnected({connectionId}){for(const holder of holders.values())if(holder.browser.connectionId===connectionId)track(revoke(holder.lease,'browser_disconnected'));}
  function revoked({sessionId}){channels.closeSession(sessionId);for(const holder of holders.values())if(holder.principal.sessionId===sessionId)track(revoke(holder.lease,'session_revoked'));}
  function unavailable(){channels.closeAll();for(const holder of holders.values())track(revoke(holder.lease,'identity_unavailable'));}
  function deviceDisconnected(context){for(const holder of holders.values())if(holder.lease.deviceId===context.deviceId&&holder.lease.deviceConnectionId===context.connectionId){channels.close(holder.browser.connectionId);track(revoke(holder.lease,'device_disconnected'));}}
  sessions.events.on('revoked',revoked);sessions.events.on('unavailable',unavailable);channels.events.on('fresh',fresh);channels.events.on('closed',disconnected);
  devices.events?.on('disconnected',deviceDisconnected);
  const timer=setInterval(()=>{if(closed)return;for(const holder of holders.values()){try{channels.requireFresh(holder.principal,holder.browser);}catch{track(revoke(holder.lease,'browser_stale'));}}},100);timer.unref();
  return api;
}
module.exports={createControlService};
