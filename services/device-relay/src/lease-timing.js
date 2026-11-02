'use strict';
const {createHash}=require('node:crypto');
const STAGES=new Set(['queued','dequeued','principal','readiness','repository','signed','dispatched','ack','failed','registered','write_callback','received','settled']);
// Opt-in, bounded diagnostics. No protocol fields or authorization decisions.
function createLeaseTiming({enabled=process.env.THIRDHAND_SDK_TIMING==='1',sink=record=>console.warn(JSON.stringify(record)),mono=()=>performance.now(),wall=()=>Date.now(),limit=12000,windowMs=600000}={}){
  let opened=null,count=0;
  return {begin(envelope=null){
    if(!enabled)return null;
    const start=mono(),startedAtMs=wall();if(opened===null)opened=start;
    if(start-opened>=windowMs||count>=limit)return null;
    let trace=null,signedAtMs=null,done=false;const marks={};
    const result={
      bind(value){try{if(typeof value?.payloadBase64url==='string'&&value.payloadBase64url.length<=16384){
        trace=createHash('sha256').update(value.payloadBase64url,'ascii').digest('hex');
        const payload=JSON.parse(Buffer.from(value.payloadBase64url,'base64url'));
        if(Number.isSafeInteger(payload.issuedAt))signedAtMs=payload.issuedAt;
      }}catch{/* Never change request outcome. */}},
      mark(stage){if(STAGES.has(stage)&&!(stage in marks)){const elapsed=mono()-start;if(Number.isFinite(elapsed))marks[stage]=Math.round(Math.max(0,Math.min(60000,elapsed))*1000)/1000;}},
      finish(segment,outcome){if(done)return;done=true;
        if(!['cloud','relay'].includes(segment)||!['active','rejected','failed','unknown'].includes(outcome)||count>=limit||mono()-opened>=windowMs)return;
        count++;try{sink(Object.freeze({component:'sdk_segment_timing',segment,trace,startedAtMs,signedAtMs,outcome,marks:Object.freeze({...marks})}));}catch{/* A diagnostic sink cannot prevent revoke. */}
      }
    };result.bind(envelope);return result;
  }};
}
module.exports={createLeaseTiming};
