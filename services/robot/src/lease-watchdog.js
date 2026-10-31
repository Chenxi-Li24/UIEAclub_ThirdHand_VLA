'use strict';

// Independent of gateway polling, but still a software/event-loop watchdog.
// It cannot run while Node/the OS is stopped and cannot itself prove motor stop.
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
function failure(code){return Object.assign(new Error(code),{code});}

class LeaseWatchdog {
  constructor({monotonic=()=>performance.now(),onExpire,schedule=setTimeout,cancel=clearTimeout}){
    if(typeof monotonic!=='function'||typeof onExpire!=='function'||typeof schedule!=='function'||typeof cancel!=='function')throw failure('WATCHDOG_CALLBACK_REQUIRED');
    this.monotonic=monotonic;this.onExpire=onExpire;this.schedule=schedule;this.cancel=cancel;
    this.deadline=null;this.generation=0;this.binding=null;this.timer=null;this.terminal=false;
    this.lastLeaseEpoch=0;this.lastMonotonic=null;this.closed=false;this.lastError=null;
  }
  _now(){
    const value=this.monotonic();
    if(!Number.isFinite(value)||value<0||this.lastMonotonic!==null&&value<this.lastMonotonic)throw failure('MONOTONIC_CLOCK_INVALID');
    this.lastMonotonic=value;return value;
  }
  reset(binding){
    if(this.closed)throw failure('WATCHDOG_CLOSED');
    if(this.deadline!==null){
      if(this._now()>=this.deadline){void this.expire();throw failure('LEASE_EXPIRED');}
      throw failure('LEASE_STILL_ACTIVE');
    }
    if(!binding||typeof binding!=='object'||Array.isArray(binding)||!UUID.test(binding.executorEpoch)||!UUID.test(binding.leaseId)
       ||typeof binding.hardwareFingerprint!=='string'||!binding.hardwareFingerprint
       ||!Number.isSafeInteger(binding.leaseEpoch)||binding.leaseEpoch<1
       ||!Object.values(binding).every(value=>typeof value==='string'||typeof value==='number'&&Number.isFinite(value)))throw failure('LEASE_BINDING_REQUIRED');
    if(binding.leaseEpoch<=this.lastLeaseEpoch)throw failure('LEASE_GENERATION_REPLAYED');
    this.clear();this.binding=Object.freeze({...binding});this.lastLeaseEpoch=binding.leaseEpoch;this.terminal=false;
  }
  renew(ttlMs,{deadline=null}={}){
    if(!Number.isFinite(ttlMs)||ttlMs<=0||ttlMs>1000)throw failure('INVALID_LEASE_TTL');
    if(this.closed||this.terminal)throw failure(this.closed?'WATCHDOG_CLOSED':'LEASE_TERMINAL');
    let current;
    try{current=this._now();}catch(error){if(this.deadline!==null)void this._trip('monotonic_clock_invalid',null);throw error;}
    if(this.deadline!==null&&current>=this.deadline){void this.expire();throw failure('LEASE_EXPIRED');}
    if(deadline!==null&&(!Number.isFinite(deadline)||deadline<0))throw failure('INVALID_LEASE_DEADLINE');
    const next=deadline===null?current+ttlMs:Math.min(current+ttlMs,deadline);
    if(next<=current)throw failure('LEASE_EXPIRED');
    if(this.timer!==null)this.cancel(this.timer);
    this.deadline=next;const ticket=++this.generation;this._schedule(ticket,next-current);
    return true;
  }
  _schedule(ticket,delay){
    this.timer=this.schedule(()=>this._timerFired(ticket),delay);this.timer?.unref?.();
  }
  async _timerFired(ticket){
    if(ticket!==this.generation||this.terminal||this.deadline===null)return false;
    this.timer=null;
    let current;
    try{current=this._now();}catch{return this._trip('monotonic_clock_invalid',null);}
    if(current<this.deadline){this._schedule(ticket,this.deadline-current);return false;}
    return this._trip('lease_expired',current);
  }
  clear(){
    if(this.timer!==null)this.cancel(this.timer);
    this.timer=null;this.deadline=null;this.terminal=true;this.generation++;
  }
  close(){this.clear();this.closed=true;}
  async _trip(reason,expiredAt){
    if(this.deadline===null||this.terminal)return false;
    const event=Object.freeze({binding:this.binding,generation:this.generation,deadline:this.deadline,expiredAt,reason});
    this.clear();
    try{await this.onExpire(event);}catch{this.lastError='EXPIRY_HANDLER_FAILED';}
    return true;
  }
  async expire(){
    if(this.deadline===null||this.terminal)return false;
    let current;
    try{current=this._now();}catch{return this._trip('monotonic_clock_invalid',null);}
    return current<this.deadline?false:this._trip('lease_expired',current);
  }
}
module.exports={LeaseWatchdog};
