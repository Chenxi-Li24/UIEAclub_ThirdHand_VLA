'use strict';
const {randomUUID,randomBytes,timingSafeEqual}=require('node:crypto');
const {EventEmitter}=require('node:events');
const {authorize}=require('../../../../platform/identity/src/policy');
const fail=code=>Object.assign(Error(code),{code});
function createBrowserControlRegistry({clock={monotonic:()=>performance.now()}}={}){
  const connections=new Map(),events=new EventEmitter();
  const find=(principal,id)=>{const item=connections.get(id);if(!item||item.principal.sessionId!==principal?.sessionId||item.principal.userId!==principal?.userId||item.principal.roleVersion!==principal?.roleVersion||!authorize(principal,'control.command').ok)throw fail('FORBIDDEN');return item;};
  return {events,
    open(principal,{clientInstanceId,send}){
      if(!authorize(principal,'control.request').ok||typeof clientInstanceId!=='string'||!/^[a-f0-9-]{36}$/i.test(clientInstanceId))throw fail('FORBIDDEN');
      const connectionId=randomUUID();connections.set(connectionId,{principal,clientInstanceId,send,sequence:0,lastResponse:-Infinity,lastSequence:0,challenges:new Map()});return {connectionId};
    },
    challenge(connectionId){const item=connections.get(connectionId);if(!item)throw fail('FORBIDDEN');const sequence=++item.sequence,nonce=randomBytes(32).toString('base64url'),message={type:'challenge',connectionId,sequence,nonce};item.challenges.set(sequence,{nonce,issued:clock.monotonic()});for(const [old,value]of item.challenges)if(old<sequence-1||clock.monotonic()-value.issued>=500)item.challenges.delete(old);item.send(message);return message;},
    respond(principal,{connectionId,sequence,nonce}){
      const item=find(principal,connectionId),pending=item.challenges.get(sequence);
      if(!Number.isSafeInteger(sequence)||sequence<=item.lastSequence||!pending||clock.monotonic()-pending.issued>=500||typeof nonce!=='string'||!/^[A-Za-z0-9_-]{43}$/.test(nonce)||!timingSafeEqual(Buffer.from(nonce),Buffer.from(pending.nonce)))throw fail('STALE_CHALLENGE');
      item.lastSequence=sequence;item.lastResponse=clock.monotonic();for(const key of item.challenges.keys())if(key<=sequence)item.challenges.delete(key);
      events.emit('fresh',{principal,binding:{connectionId,clientInstanceId:item.clientInstanceId},sequence});return true;
    },
    requireFresh(principal,{connectionId,clientInstanceId}){const item=find(principal,connectionId);if(item.clientInstanceId!==clientInstanceId)throw fail('FORBIDDEN');if(clock.monotonic()-item.lastResponse>=500)throw fail('BROWSER_STALE');return true;},
    close(connectionId){const item=connections.get(connectionId);if(!item)return;connections.delete(connectionId);events.emit('closed',{connectionId,principal:item.principal});},
    closeSession(sessionId){for(const [id,item]of connections)if(item.principal.sessionId===sessionId)this.close(id);},
    closeAll(){for(const id of [...connections.keys()])this.close(id);}
  };
}
module.exports={createBrowserControlRegistry};
