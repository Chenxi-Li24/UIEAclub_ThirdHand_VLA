'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {LeaseWatchdog}=require('../../../services/robot/src/lease-watchdog');

function fixture(){
  let mono=100;
  const calls=[],timers=[];
  const watchdog=new LeaseWatchdog({monotonic:()=>mono,onExpire:async value=>calls.push(value),
    schedule:(fn,delay)=>{const timer={fn,delay,cancelled:false,unref(){this.unreferenced=true;}};timers.push(timer);return timer;},
    cancel:timer=>{timer.cancelled=true;}});
  const binding={executorEpoch:randomUUID(),hardwareFingerprint:'a'.repeat(64),leaseId:randomUUID(),leaseEpoch:1,
    deviceId:randomUUID(),bootId:randomUUID(),connectionId:randomUUID(),certificateId:randomUUID()};
  return {watchdog,calls,timers,binding,advance:value=>{mono=value;}};
}

test('first lease arms an autonomous unreferenced deadline without gateway polling',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.watchdog.renew(950);
  assert.equal(f.timers.length,1);assert.equal(f.timers[0].delay,950);assert.equal(f.timers[0].unreferenced,true);
  f.advance(1050);await f.timers[0].fn();
  assert.equal(f.calls.length,1);assert.deepEqual(f.calls[0].binding,f.binding);
  assert.equal(f.calls[0].reason,'lease_expired');assert.equal(f.calls[0].deadline,1050);
  assert.equal(await f.watchdog.expire(),false);
});

test('an overdue lease cannot be revived even before its timer callback executes',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.watchdog.renew(100);f.advance(200);
  assert.throws(()=>f.watchdog.renew(1000),{code:'LEASE_EXPIRED'});
  await new Promise(setImmediate);assert.equal(f.calls.length,1);
  assert.equal(f.watchdog.deadline,null);
});

test('clear and expiry are terminal for that lease; only a higher explicit lease generation may arm',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.watchdog.renew(100);f.watchdog.clear();
  assert.throws(()=>f.watchdog.renew(100),{code:'LEASE_TERMINAL'});
  assert.throws(()=>f.watchdog.reset(f.binding),{code:'LEASE_GENERATION_REPLAYED'});
  assert.throws(()=>f.watchdog.reset({...f.binding,connectionId:randomUUID()}),{code:'LEASE_GENERATION_REPLAYED'});
  f.watchdog.reset({...f.binding,leaseId:randomUUID(),leaseEpoch:2});f.watchdog.renew(100);
  f.advance(200);await f.watchdog.expire();assert.equal(f.calls.length,1);
  assert.throws(()=>f.watchdog.renew(100),{code:'LEASE_TERMINAL'});
});

test('old queued timer cannot expire a replacement lease or repeat a stop',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.watchdog.renew(100);const first=f.timers[0];
  f.advance(150);f.watchdog.renew(200);assert.equal(first.cancelled,true);
  f.advance(210);await first.fn();assert.equal(f.calls.length,0);
  f.watchdog.clear();f.watchdog.reset({...f.binding,leaseEpoch:2});f.watchdog.renew(100);
  f.advance(400);await first.fn();assert.equal(f.calls.length,0);
  await f.timers.at(-1).fn();assert.equal(f.calls.length,1);
});

test('binding is a copied immutable snapshot and active reset is rejected',()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.binding.connectionId=randomUUID();f.watchdog.renew(100);
  assert.throws(()=>f.watchdog.reset({...f.binding,leaseEpoch:2}),{code:'LEASE_STILL_ACTIVE'});
});

test('early timer firing schedules only the remaining monotonic lifetime',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.watchdog.renew(1000);f.advance(300);
  await f.timers[0].fn();assert.equal(f.calls.length,0);assert.equal(f.timers.at(-1).delay,800);
  f.advance(1100);await f.timers.at(-1).fn();assert.equal(f.calls.length,1);
});

test('bounded TTL and invalid monotonic clock fail closed without inventing a deadline',()=>{
  const f=fixture();for(const bad of [0,-1,1001,Infinity,NaN,'950'])assert.throws(()=>f.watchdog.renew(bad));
  f.watchdog.reset(f.binding);f.advance(NaN);assert.throws(()=>f.watchdog.renew(950),{code:'MONOTONIC_CLOCK_INVALID'});
});

test('a precomputed monotonic expiry cap cannot be extended by later scheduling delay',async()=>{
  const f=fixture();f.watchdog.reset(f.binding);f.advance(600);f.watchdog.renew(950,{deadline:1050});
  assert.equal(f.watchdog.deadline,1050);assert.equal(f.timers[0].delay,450);
  f.advance(1050);await f.timers[0].fn();assert.equal(f.calls.length,1);
  f.watchdog.reset({...f.binding,leaseEpoch:2});assert.throws(()=>f.watchdog.renew(950,{deadline:1000}),{code:'LEASE_EXPIRED'});
});
