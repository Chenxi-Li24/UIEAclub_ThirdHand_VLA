'use strict';
const {randomUUID}=require('node:crypto');
const {authorize}=require('../../../../platform/identity/src/policy');
const {compactNegotiation,publicationExpiry,compactResponse}=require('./compact-grant');
const fail=code=>Object.assign(Error(code),{code});
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const object=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&Object.keys(value).every(key=>keys.includes(key));
function createMediaService({sessions,devices,provider,signer,clock={now:()=>Date.now(),monotonic:()=>performance.now()},maxViewers=10,startTimer=true}){
  const viewers=new Map(),publishers=new Map(),pending=new Set(),publisherBusy=new Set();let identityHealthy=true,closed=false,ticking=false;
  const wall=()=>Number(clock.now()),mono=()=>clock.monotonic();
  const current=context=>{const actual=devices.get(context.deviceId);return !!actual&&BINDING.every(key=>actual[key]===context[key]);};
  const allowed=principal=>{if(closed||!identityHealthy||!authorize(principal,'video.view').ok)throw fail('FORBIDDEN');};
  function track(promise){pending.add(promise);promise.catch(()=>{}).finally(()=>pending.delete(promise));return promise;}
  const held=deviceId=>[...viewers.values()].some(item=>item.deviceId===deviceId&&item.revoked&&!item.removed);
  const publishing=item=>!!item&&!closed&&identityHealthy&&current(item.context)&&mono()<item.deadline&&!held(item.context.deviceId);
  function clearCompact(item){if(item){item.credentialCache=null;if(item.compactNegotiated){item.compactFailed=true;item.deadline=-Infinity;}}}
  function fresh(frame){
    if(!frame||mono()-frame.receivedAt>500||mono()<frame.receivedAt||frame.clockQuality==='unreliable')return false;
    const age=wall()-Number(BigInt(frame.capturedAtUs)/1000n);
    return age>=-frame.uncertaintyMs&&age+frame.uncertaintyMs<=500;
  }
  async function remove(item){
    item.revoked=true;
    if(item.removed||item.removing)return item.removing;
    item.lastRemoval=mono();
    const operation=(async()=>{try{await provider.removeParticipant(item.room,item.identity);item.removed=true;if(viewers.get(item.id)===item)viewers.delete(item.id);}catch{clearCompact(publishers.get(item.deviceId));/* Keep the upstream publication hold until a trusted removal ACK. */}})();
    item.removing=operation;track(operation);try{await operation;}finally{item.removing=null;}
  }
  function revokeSession({sessionId}){for(const item of viewers.values())if(item.principal.sessionId===sessionId)void remove(item);}
  function unavailable(){identityHealthy=false;for(const item of publishers.values())clearCompact(item);for(const item of viewers.values())void remove(item);}
  function disconnected(context){const publisher=publishers.get(context.deviceId);if(publisher&&BINDING.every(key=>publisher.context[key]===context[key])){clearCompact(publisher);publisher.deadline=-Infinity;for(const item of viewers.values())if(item.deviceId===context.deviceId)void remove(item);}}
  sessions.events.on('revoked',revokeSession);sessions.events.on('unavailable',unavailable);devices.events?.on('disconnected',disconnected);
  async function tick(){
    if(ticking||closed)return;ticking=true;
    try{for(const item of viewers.values()){
      if(item.revoked){if(!item.removed&&!item.removing&&mono()-item.lastRemoval>=1000)void remove(item);continue;}
      let principal;try{principal=await sessions.resolveSession(item.request);}catch{unavailable();break;}
      if(!principal||principal.sessionId!==item.principal.sessionId||!authorize(principal,'video.view').ok||wall()>=item.expiresAt||!current(item.context))void remove(item);
    }}finally{ticking=false;}
  }
  const timer=startTimer?setInterval(()=>void tick(),250):null;timer?.unref();
  const api={
    async acceptPublisher(context,value,negotiation=null){
      if(!context||closed||!identityHealthy||!current(context)||!BINDING.every(key=>key==='executorEpoch'&&context[key]===null||UUID.test(context[key])))throw fail('DEVICE_UNAVAILABLE');
      if(!object(value,['publisherId','sequence','frame'])||!UUID.test(value.publisherId)||!Number.isSafeInteger(value.sequence)||value.sequence<1)throw fail('INVALID_INPUT');
      if(publisherBusy.has(context.deviceId))throw fail('MEDIA_BUSY');publisherBusy.add(context.deviceId);
      try{
      if(held(context.deviceId))throw fail('MEDIA_REVOCATION_PENDING');
      let item=publishers.get(context.deviceId);
      if(!item||item.id!==value.publisherId||!BINDING.every(key=>item.context[key]===context[key])){
        if(item&&publishing(item))throw fail('MEDIA_PUBLISHER_BUSY');
        if(item){for(const viewer of viewers.values())if(viewer.deviceId===context.deviceId&&!viewer.revoked)void remove(viewer);if(held(context.deviceId))throw fail('MEDIA_REVOCATION_PENDING');}
        const room='d_'+context.deviceId+'_'+randomUUID();await provider.ensureRoom?.(room);
        item={id:value.publisherId,context:{...context},identity:'p_'+value.publisherId,room,sequence:0,frames:new Map(),lastFrame:null,deadline:-Infinity,token:null,tokenAt:-Infinity,compactNegotiated:false,compactFailed:false,credentialCache:null};publishers.set(context.deviceId,item);
      }
      if(item.compactNegotiated&&(item.compactFailed||mono()>=item.deadline))throw fail('MEDIA_LEASE_EXPIRED');
      const previousDeadline=item.compactNegotiated?item.deadline:null,negotiated=compactNegotiation(negotiation);
      if(negotiated)item.compactNegotiated=true;
      if(!current(context)||value.sequence<=item.sequence)throw fail('INVALID_INPUT');
      const frame=value.frame;
      if(frame!==null){
        if(!object(frame,['frameId','capturedAtUs','clockQuality','uncertaintyMs'])||typeof frame.frameId!=='string'||!/^\d{1,19}$/.test(frame.frameId)||typeof frame.capturedAtUs!=='string'||!/^\d{1,19}$/.test(frame.capturedAtUs)||!['synchronized','estimated','unreliable'].includes(frame.clockQuality)||!Number.isFinite(frame.uncertaintyMs)||frame.uncertaintyMs<0||frame.uncertaintyMs>60000)throw fail('INVALID_INPUT');
        if(item.lastFrame&&BigInt(frame.frameId)<BigInt(item.lastFrame.frameId))throw fail('INVALID_INPUT');
        if(!item.lastFrame||BigInt(frame.frameId)>BigInt(item.lastFrame.frameId)){
          item.lastFrame={...frame,receivedAt:mono()};item.frames.set(frame.frameId,item.lastFrame);if(item.frames.size>32)item.frames.delete(item.frames.keys().next().value);
        }else if(frame.capturedAtUs!==item.lastFrame.capturedAtUs)throw fail('INVALID_INPUT');
      }
      item.sequence=value.sequence;
      if(!item.token||mono()-item.tokenAt>=20000){item.token=await provider.publisherToken({identity:item.identity,room:item.room});item.tokenAt=mono();}
      if((negotiated||item.compactNegotiated)&&(publicationExpiry(item.token,item,wall())??-Infinity)<wall()+950){item.token=await provider.publisherToken({identity:item.identity,room:item.room});item.tokenAt=mono();}
      if(held(context.deviceId)||!current(context)||!identityHealthy)throw fail('MEDIA_REVOCATION_PENDING');
      const issuedMono=mono(),now=wall(),grantDeadline=issuedMono+950,payload={schema:1,purpose:'media_publish',...context,publisherId:item.id,sequence:item.sequence,room:item.room,identity:item.identity,token:item.token,sourceFresh:fresh(item.lastFrame),frame:item.lastFrame?{frameId:item.lastFrame.frameId,capturedAtUs:item.lastFrame.capturedAtUs,clockQuality:item.lastFrame.clockQuality,uncertaintyMs:item.lastFrame.uncertaintyMs}:null,issuedAt:now,expiresAt:now+950};
      const full=signer.sign(payload);let result=full,nextCache=item.credentialCache;
      if(negotiated||item.compactNegotiated){const compact=compactResponse({signer,payload,full,cache:item.credentialCache,negotiation,now,monotonic:issuedMono});nextCache=compact.cache;result=compact.envelope;}
      // Awaited JWT creation and synchronous signing must not revive a prior
      // expired/invalidated publication, or extend this grant after issuance.
      const committedWall=wall(),committedMono=mono();
      if(publishers.get(context.deviceId)!==item||item.compactFailed||previousDeadline!==null&&committedMono>=previousDeadline||committedMono>=grantDeadline||committedWall>=payload.expiresAt)throw fail('MEDIA_LEASE_EXPIRED');
      if(held(context.deviceId)||!current(context)||!identityHealthy)throw fail('MEDIA_REVOCATION_PENDING');
      item.credentialCache=nextCache;item.deadline=grantDeadline;return result;
      }catch(error){const item=publishers.get(context.deviceId);if(item?.id===value.publisherId&&BINDING.every(key=>item.context[key]===context[key]))clearCompact(item);throw error;}
      finally{publisherBusy.delete(context.deviceId);}
    },
    async issueViewGrant(principal,request,{deviceId}){
      allowed(principal);if(!UUID.test(deviceId))throw fail('INVALID_INPUT');
      const source=publishers.get(deviceId);if(!publishing(source))throw fail('MEDIA_UNAVAILABLE');
      const active=[...viewers.values()].filter(item=>!item.revoked);if(active.length>=maxViewers||active.filter(item=>item.principal.sessionId===principal.sessionId).length>=4)throw fail('MEDIA_BUSY');
      const id=randomUUID(),item={id,identity:'v_'+id,principal,request,context:source.context,deviceId,room:source.room,expiresAt:wall()+8*3600000,revoked:false,removed:false,lastRendered:null,lastFrameId:null};
      viewers.set(id,item);let token;
      try{token=await provider.viewToken({identity:item.identity,room:item.room});
        const actual=await sessions.resolveSession(request);if(item.revoked||actual?.sessionId!==principal.sessionId||!authorize(actual,'video.view').ok||!publishing(source))throw fail('FORBIDDEN');
      }catch(error){if(!item.revoked)viewers.delete(id);throw error;}
      // Token is returned only to this authenticated request, kept in tab memory,
      // and still requires the same session at the reverse-proxy signal gate.
      viewers.set(id,item);return {viewerId:id,deviceId,token,serverUrl:'/media',room:source.room,identity:item.identity,publisherIdentity:source.identity,expiresAt:new Date(item.expiresAt).toISOString()};
    },
    async authorizeSignaling(token,principal){
      if(closed||!identityHealthy||typeof token!=='string'||token.length>8192)throw fail('FORBIDDEN');let claims;
      try{claims=await provider.verifyToken(token);}catch{throw fail('FORBIDDEN');}
      const video=claims.video;
      if(!video||video.roomJoin!==true||video.roomAdmin||video.roomCreate||video.roomRecord||video.ingressAdmin||video.canPublishData!==false||video.canUpdateOwnMetadata!==false)throw fail('FORBIDDEN');
      const id=typeof claims.sub==='string'?claims.sub.slice(2):'',item=viewers.get(id);
      if(claims.sub?.startsWith('v_')&&item&&!item.revoked&&wall()<item.expiresAt&&item.identity===claims.sub&&video.room===item.room&&video.canPublish===false&&video.canSubscribe===true&&principal?.sessionId===item.principal.sessionId&&authorize(principal,'video.view').ok&&publishing(publishers.get(item.deviceId)))return {kind:'viewer',id:item.id};
      const publisher=[...publishers.values()].find(value=>value.id===id);
      if(claims.sub?.startsWith('p_')&&publisher&&publishing(publisher)&&publisher.identity===claims.sub&&video.room===publisher.room&&video.canPublish===true&&video.canSubscribe===false&&Array.isArray(video.canPublishSources)&&video.canPublishSources.length===1&&video.canPublishSources[0]==='camera')return {kind:'publisher',id:publisher.id};
      throw fail('FORBIDDEN');
    },
    async reportViewFrame(principal,value){
      allowed(principal);if(!object(value,['viewerId','frameId','capturedAtUs'])||!UUID.test(value.viewerId)||typeof value.frameId!=='string'||typeof value.capturedAtUs!=='string')throw fail('INVALID_INPUT');
      const item=viewers.get(value.viewerId),source=item&&publishers.get(item.deviceId),frame=source?.frames.get(value.frameId);
      if(!item||item.revoked||item.principal.sessionId!==principal.sessionId)throw fail('FORBIDDEN');
      if(!publishing(source)||item.room!==source.room||!current(item.context)||!frame||frame.capturedAtUs!==value.capturedAtUs||!fresh(frame)||item.lastFrameId!==null&&BigInt(value.frameId)<=BigInt(item.lastFrameId))throw fail('STALE_VIDEO_FRAME');
      item.lastFrameId=value.frameId;item.lastRendered=mono();return {accepted:true};
    },
    videoReadiness(principal,deviceId){
      const source=publishers.get(deviceId);return publishing(source)&&fresh(source.lastFrame)&&[...viewers.values()].some(item=>item.deviceId===deviceId&&item.room===source.room&&current(item.context)&&!item.revoked&&item.principal.sessionId===principal?.sessionId&&item.lastRendered!==null&&mono()-item.lastRendered<500&&fresh(source.frames.get(item.lastFrameId)));
    },
    async closeViewer(principal,id){allowed(principal);const item=viewers.get(id);if(!item||item.principal.sessionId!==principal.sessionId)throw fail('NOT_FOUND');await remove(item);return {closed:item.removed};},
    status(deviceId){const source=publishers.get(deviceId);return {deviceId,available:publishing(source),sourceFresh:publishing(source)&&fresh(source.lastFrame),frame:source?.lastFrame?{frameId:source.lastFrame.frameId,capturedAtUs:source.lastFrame.capturedAtUs,clockQuality:source.lastFrame.clockQuality,uncertaintyMs:source.lastFrame.uncertaintyMs}:null};},
    // Internal evidence for a separately commissioned robot/camera association.
    // This is not an HTTP endpoint and contains no SFU token or operator grant.
    motionSourceEvidence(deviceId){const source=publishers.get(deviceId);if(!publishing(source))return null;
      const frame=source.lastFrame?Object.freeze({frameId:source.lastFrame.frameId,capturedAtUs:source.lastFrame.capturedAtUs,clockQuality:source.lastFrame.clockQuality,uncertaintyMs:source.lastFrame.uncertaintyMs}):null;
      return Object.freeze({context:Object.freeze({...source.context}),sourceFresh:fresh(source.lastFrame),frame});},
    tick,async drain(){while(pending.size)await Promise.allSettled([...pending]);},
    async close(){if(closed)return;closed=true;if(timer)clearInterval(timer);sessions.events.off('revoked',revokeSession);sessions.events.off('unavailable',unavailable);devices.events?.off('disconnected',disconnected);for(const item of publishers.values())clearCompact(item);for(const item of viewers.values())void remove(item);await api.drain();}
  };
  return api;
}
module.exports={createMediaService};
