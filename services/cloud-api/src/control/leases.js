'use strict';
const {randomUUID,randomBytes,createHash}=require('node:crypto');
const {authorize}=require('../../../../platform/identity/src/policy');
const {validOperation}=require('../../../robot/src/control-policy');
const {createLeaseTiming}=require('../../../device-relay/src/lease-timing');
const fail=code=>Object.assign(Error(code),{code});
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const same=(left,right)=>left&&right&&BINDING.every(key=>left[key]===right[key]);
const hash=value=>createHash('sha256').update(value).digest('hex');
function createControlService({repository,sessions,channels,devices,signer,clock={now:()=>new Date(),monotonic:()=>performance.now()},readiness=async()=>false,onDiagnostic=()=>{},timing=createLeaseTiming()}){
  const holders=new Map(),pending=new Set(),revocations=new Map();let closed=false;
  const diagnosticCodes=new Set(['FORBIDDEN','BROWSER_STALE','LEASE_CHANGED','LEASE_REQUIRED','DEVICE_UNAVAILABLE','DEVICE_REPLY_UNKNOWN','DEVICE_DISCONNECTED','DEVICE_BUSY','LEASE_UNCONFIRMED']);
  const deviceCodes=new Set(['DEVICE_REQUEST_REJECTED','SUBMISSION_RESULT_UNKNOWN','POLICY_CLOSED','WRONG_EXECUTOR','EXPIRED_COMMAND','STOP_UNCONFIRMED','LEASE_UPDATE_PENDING','INVALID_LEASE','INVALID_LEASE_SCOPE','LEASE_SCOPE_CHANGED','LEASE_CONFLICT','STALE_LEASE','LEASE_EXPIRED','LOCAL_LEASE_GUARD_REJECTED']);
  function reportConfirmation(phase,result,lease){
    // Only constants and comparisons cross this boundary, never response values
    // outside the allowlists (including identifiers or arbitrary error strings).
    try{onDiagnostic(Object.freeze({component:'sdk_lease_confirmation',phase,
      deviceState:['active','rejected','failed','unknown'].includes(result?.state)?result.state:'UNRECOGNIZED',
      deviceCode:deviceCodes.has(result?.code)?result.code:'UNRECOGNIZED',
      leaseIdMatches:result?.leaseId===lease.id,leaseEpochMatches:result?.leaseEpoch===lease.leaseEpoch,
      scopeMatches:result?.scope===lease.scope}));}catch{/* Diagnostics cannot affect revocation. */}
  }
  function reportRenewal(stage,error,started){
    // Never pass arbitrary exceptions, principals, envelopes or identifiers to logs.
    try{onDiagnostic(Object.freeze({component:'sdk_renewal',stage,code:diagnosticCodes.has(error?.code||error?.message)?(error.code||error.message):'RENEWAL_FAILED',elapsedMs:Math.max(0,Math.min(60000,Math.round(clock.monotonic()-started)))}));}catch{/* Diagnostics cannot affect authorization. */}
  }
  function track(promise){pending.add(promise);promise.catch(()=>{}).finally(()=>pending.delete(promise));return promise;}
  async function actor(principal,action,binding){if(!authorize(principal,action).ok)throw fail('FORBIDDEN');await repository.validatePrincipal(principal,action.startsWith('sdk.')?'sdk':'control');if(binding)channels.requireFresh(principal,binding);}
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
      const result=await devices.request(lease.deviceId,signed('lease_grant',binding,{leaseId:lease.id,leaseEpoch:lease.leaseEpoch,sequence:0,scope:lease.scope},lease.scope==='sdk'?3000:1000));
      if(result?.state!=='active'||result.leaseId!==lease.id||result.leaseEpoch!==lease.leaseEpoch||(lease.scope==='sdk'&&result.scope!=='sdk')){reportConfirmation('grant',result,lease);throw fail('LEASE_UNCONFIRMED');}
      await actor(principal,lease.scope==='sdk'?'sdk.connect':'control.request',browser);
      if(!same(context(lease.deviceId),binding)||!await readiness(principal,lease.deviceId))throw fail('DEVICE_UNAVAILABLE');
      const active=await repository.confirm(principal,lease.id);holders.set(active.id,{lease:active,principal,browser,lastRenewalScheduledAt:clock.monotonic()});return active;
    }catch(error){await revoke(lease,'grant_failed');throw error;}
  }
  function dispatchRenewal(principal,input,holder){
    const trace=holder.lease.scope==='sdk'?timing.begin():null;
    trace?.mark('queued');
    // Serialize principal/DB checks and writes to the ordered device channel,
    // but do not occupy the send queue while awaiting the return-path ACK.
    const dispatch=(holder.dispatch||Promise.resolve()).catch(()=>{}).then(async()=>{
      trace?.mark('dequeued');
      const started=clock.monotonic();let stage='principal';
      const stillHeld=()=>{if(holders.get(holder.lease.id)!==holder)throw fail('LEASE_CHANGED');channels.requireFresh(principal,input);};
      try{
        stillHeld();await actor(principal,holder.lease.scope==='sdk'?'sdk.connect':'control.command',input);
        trace?.mark('principal');
        stage='readiness';stillHeld();
        const binding=context(input.deviceId);
        if(!same(binding,leaseContext(holder.lease))||!await readiness(principal,input.deviceId)){await revoke(holder.lease,'readiness_lost');throw fail('DEVICE_UNAVAILABLE');}
        trace?.mark('readiness');
        stage='repository';stillHeld();
        const renewed=await repository.renew(principal,holder.lease.id);
        trace?.mark('repository');
        stage='dispatch';stillHeld();
        if(!same(context(input.deviceId),binding))throw fail('DEVICE_UNAVAILABLE');
        stage='device_reply';
        const envelope=signed('lease_renew',binding,{leaseId:renewed.id,leaseEpoch:renewed.leaseEpoch,sequence:renewed.renewalSequence,scope:renewed.scope},renewed.scope==='sdk'?3000:1000);
        trace?.bind(envelope);trace?.mark('signed');
        // A legacy adapter without a send-completion boundary remains serialized.
        const response=typeof devices.dispatch==='function'?(await devices.dispatch(input.deviceId,envelope)).confirmation:Promise.resolve(await devices.request(input.deviceId,envelope));
        trace?.mark('dispatched');
        const confirmation=(async()=>{
          try{
            const result=await response;stage='confirmation';
            trace?.mark('ack');trace?.finish('cloud',['active','rejected','failed'].includes(result?.state)?result.state:'unknown');
            if(result?.state!=='active'||result.leaseId!==renewed.id||result.leaseEpoch!==renewed.leaseEpoch||(renewed.scope==='sdk'&&result.scope!=='sdk')){reportConfirmation('renewal',result,renewed);await revoke(renewed,'renewal_unconfirmed');throw fail('LEASE_UNCONFIRMED');}
            stillHeld();
            // ACKs may arrive in a different order; never regress holder state.
            if(renewed.renewalSequence>holder.lease.renewalSequence)holder.lease=renewed;
            return {renewed:true};
          }catch(error){trace?.mark('failed');trace?.finish('cloud','failed');reportRenewal(stage,error,started);throw error;}
        })();
        confirmation.catch(()=>{});
        return {confirmation};
      }catch(error){trace?.mark('failed');trace?.finish('cloud','failed');reportRenewal(stage,error,started);throw error;}
    });
    holder.dispatch=dispatch;return dispatch;
  }
  const api={
    async listDevices(principal){if(!authorize(principal,'telemetry.read').ok)throw fail('FORBIDDEN');const rows=await repository.listDevices();return rows.map(row=>({...row,online:!!devices.get(row.id),controlAccepted:devices.get(row.id)?.controlAccepted===true,readOnly:devices.get(row.id)?.readOnly===true}));},
    async status(principal,deviceId){await actor(principal,'sdk.connect');const lease=await repository.current(deviceId);return {deviceId,online:!!devices.get(deviceId),controlAccepted:devices.get(deviceId)?.controlAccepted===true,lease:lease?{leaseEpoch:lease.leaseEpoch,state:lease.state,own:lease.sessionId===principal.sessionId}:null};},
    async requestLease(principal,input){
      await actor(principal,'sdk.connect',input);const binding=context(input.deviceId);
      if(!await readiness(principal,input.deviceId))throw fail('CONTROL_READINESS_REQUIRED');
      const lease=await repository.reserve(principal,{context:binding,clientInstanceId:input.clientInstanceId,connectionId:input.connectionId});
      return grant(principal,lease,input,binding);
    },
    async renewFromBrowser(principal,input){
      if(!authorize(principal,'sdk.connect').ok)throw fail('FORBIDDEN');channels.requireFresh(principal,input);
      const holder=[...holders.values()].find(value=>value.lease.deviceId===input.deviceId&&value.lease.sessionId===principal.sessionId&&value.browser.connectionId===input.connectionId&&value.browser.clientInstanceId===input.clientInstanceId);
      if(!holder)throw fail('LEASE_REQUIRED');
      if(holder.renewal)return holder.renewal;
      holder.renewal=dispatchRenewal(principal,input,holder).then(({confirmation})=>confirmation);
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
      await actor(principal,['connect','disconnect'].includes(input.opcode)?'sdk.'+input.opcode:'control.command',input);const binding=context(input.deviceId);
      if(!await readiness(principal,input.deviceId))throw fail('CONTROL_READINESS_REQUIRED');
      if(typeof input.commandId!=='string'||!/^[a-f0-9-]{36}$/i.test(input.commandId)||!validOperation(input.opcode,input.parameters)||input.opcode==='software_stop')throw fail('INVALID_INPUT');
      if(devices.get(input.deviceId)?.readOnly===true&&!['connect','disconnect'].includes(input.opcode))throw fail('READ_ONLY_DEVICE');
      const lease=await repository.find(input.leaseId);
      if(!lease||lease.deviceId!==input.deviceId||!same(binding,leaseContext(lease))||lease.scope==='sdk'&&!['connect','disconnect'].includes(input.opcode))throw fail('FORBIDDEN');
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
  function pump(holder){
    if(holder.pumping||closed||holders.get(holder.lease.id)!==holder)return;
    holder.pumping=true;
    track((async()=>{
      try{while(holder.freshPending&&holders.get(holder.lease.id)===holder&&(holder.inflight||0)<4){
        holder.freshPending=false;holder.inflight=(holder.inflight||0)+1;
        let confirmation;
        try{({confirmation}=await dispatchRenewal(holder.principal,{...holder.browser,deviceId:holder.lease.deviceId},holder));}
        catch(error){holder.inflight--;throw error;}
        track(confirmation.catch(async()=>{if(holders.get(holder.lease.id)===holder)await revoke(holder.lease,'renewal_failed');}).finally(()=>{
          holder.inflight--;
          if(holder.freshPending)pump(holder);
        }));
      }}catch{if(holders.get(holder.lease.id)===holder)await revoke(holder.lease,'renewal_failed');}
      finally{
        holder.pumping=false;
        if(holder.freshPending&&holders.get(holder.lease.id)===holder&&(holder.inflight||0)<4)pump(holder);
      }
    })());
  }
  function fresh({binding}){
    for(const holder of holders.values())if(holder.browser.connectionId===binding.connectionId){
      // At most four signed renewals await ACK and one latest fresh event waits.
      scheduleRenewal(holder);
    }
  }
  function scheduleRenewal(holder){
    // SDK-only leases bridge short browser jitter, never a lost/expired browser.
    // Every dispatch still revalidates identity, freshness, device and DB lease.
    if(holder.lease.scope==='sdk'&&clock.monotonic()-holder.lastRenewalScheduledAt<250)return;
    holder.lastRenewalScheduledAt=clock.monotonic();holder.freshPending=true;pump(holder);
  }
  function disconnected({connectionId}){for(const holder of holders.values())if(holder.browser.connectionId===connectionId)track(revoke(holder.lease,'browser_disconnected'));}
  function revoked({sessionId}){channels.closeSession(sessionId);for(const holder of holders.values())if(holder.principal.sessionId===sessionId)track(revoke(holder.lease,'session_revoked'));}
  function unavailable(){channels.closeAll();for(const holder of holders.values())track(revoke(holder.lease,'identity_unavailable'));}
  function deviceDisconnected(context){for(const holder of holders.values())if(holder.lease.deviceId===context.deviceId&&holder.lease.deviceConnectionId===context.connectionId){channels.close(holder.browser.connectionId);track(revoke(holder.lease,'device_disconnected'));}}
  sessions.events.on('revoked',revoked);sessions.events.on('unavailable',unavailable);channels.events.on('fresh',fresh);channels.events.on('closed',disconnected);
  devices.events?.on('disconnected',deviceDisconnected);
  const timer=setInterval(()=>{if(closed)return;for(const holder of holders.values()){try{channels.requireFresh(holder.principal,holder.browser);if(holder.lease.scope==='sdk')scheduleRenewal(holder);}catch{track(revoke(holder.lease,'browser_stale'));}}},100);timer.unref();
  return api;
}
module.exports={createControlService};
