'use strict';

const WINDOW_NS = 1_000_000_000;
const MAX_GAP_NS = 250_000_000;
const vector = (a,n) => Array.isArray(a) && a.length===n && a.every(Number.isFinite);
function quaternion([roll,pitch,yaw]) {
  const [cr,cp,cy]=[roll,pitch,yaw].map(v=>Math.cos(v/2));
  const [sr,sp,sy]=[roll,pitch,yaw].map(v=>Math.sin(v/2));
  return [sr*cp*cy-cr*sp*sy, cr*sp*cy+sr*cp*sy, cr*cp*sy-sr*sp*cy, cr*cp*cy+sr*sp*sy];
}

// Calibration-only observation gate. Does not change the motion client's gates.
// A one-second window must contain >= 10 distinct frames, with no gap > 250 ms.
// Limits apply to the WHOLE window, so slow cumulative drift cannot pass.
class CalibrationPoseStability {
  constructor() { this.reset(); }
  reset() { this.frames=[]; this.stable=false; }
  eligible(s) {
    return s?.connected===true && s.healthy===true && s.stateFresh===true
      && s.moving===false && s.teachActive===false && typeof s.streamId==='string'
      && s.streamId.length>0 && Number.isSafeInteger(s.stateSequence)
      && Number.isSafeInteger(s.producerMonotonicNs)
      && vector(s.jointsDeg,6) && vector(s.flangePositionM,3) && vector(s.flangeEulerRad,3);
  }
  observe(s) {
    if(!this.eligible(s)) { this.reset(); return; }
    const previous=this.frames.at(-1), t=s.producerMonotonicNs;
    if(previous && (s.streamId!==previous.streamId || s.stateSequence<=previous.seq
      || t<=previous.t || t-previous.t>MAX_GAP_NS)) this.reset();
    this.frames.push({seq:s.stateSequence,streamId:s.streamId,t,
      j:[...s.jointsDeg],p:[...s.flangePositionM],q:quaternion(s.flangeEulerRad)});
    while(this.frames.length>1 && this.frames[1].t<=t-WINDOW_NS) this.frames.shift();
    // Bound storage even for malformed high-rate sources.
    if(this.frames.length>256) { this.reset(); return; }
    this.stable=this.frames.length>=10 && t-this.frames[0].t>=WINDOW_NS;
    for(let i=0;this.stable && i<this.frames.length;i++) {
      const a=this.frames[i];
      for(let k=i+1;k<this.frames.length;k++) {
        const b=this.frames[k];
        const dot=Math.abs(a.q.reduce((sum,v,n)=>sum+v*b.q[n],0));
        if(a.j.some((v,n)=>Math.abs(v-b.j[n])>0.03)
          || Math.hypot(...a.p.map((v,n)=>v-b.p[n]))>0.00025
          || 2*Math.acos(Math.min(1,dot))>0.05*Math.PI/180) { this.stable=false; break; }
      }
    }
  }
  ready(s) {
    const last=this.frames.at(-1);
    return this.eligible(s) && this.stable && last?.seq===s.stateSequence
      && last.t===s.producerMonotonicNs && last.streamId===s.streamId;
  }
}
module.exports={CalibrationPoseStability};
