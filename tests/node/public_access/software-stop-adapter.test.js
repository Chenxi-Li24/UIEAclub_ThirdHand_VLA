'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');

function factory(){return require('../../../services/robot/src/software-stop-adapter').createSoftwareStopAdapter;}
function fixture(options={}){
  const calls=[],timers=[];let mono=100,wall=10000;
  const state={executorEpoch:randomUUID(),hardwareFingerprint:'a'.repeat(64)};
  const request={...state,commandId:randomUUID(),leaseId:randomUUID(),leaseEpoch:1,reason:'lease_expired'};
  const adapter=factory()({getExecutionState:()=>({...state}),releaseSdk:async value=>{calls.push(value);return {sdk_released:true,stopped:true,depowered:true};},
    clock:{monotonic:()=>mono,now:()=>wall},timeoutMs:1000,
    schedule:(fn,delay)=>{const value={fn,delay,unref(){}};timers.push(value);return value;},cancel:()=>{},...options});
  return {adapter,state,request,calls,timers,advance:(m,w=wall)=>{mono=m;wall=w;}};
}

test('unsupported native stop uses real SDK-release callback but never turns cleanup flags into physical confirmation',async()=>{
  const f=fixture();const result=await f.adapter.stop(f.request);
  assert.equal(f.calls.length,1);assert.deepEqual(f.calls[0],{...f.request,requestedAt:10000});
  assert.equal(result.state,'unknown');assert.equal(result.code,'CONTROLLED_STOP_UNSUPPORTED');
  assert.equal(result.sdkReleased,true);assert.equal(result.depowered,false);
  assert.equal(f.adapter.capabilities().controlledStop,false);
});

test('stop context must match original executor before any callback can run',async()=>{
  const f=fixture();f.state.executorEpoch=randomUUID();
  assert.equal((await f.adapter.stop(f.request)).code,'WRONG_EXECUTOR');assert.equal(f.calls.length,0);
});

test('one request is idempotent and another concurrent request cannot reuse its result or queue SDK work',async()=>{
  let finish;const f=fixture({releaseSdk:()=>new Promise(resolve=>{finish=resolve;})});
  const first=f.adapter.stop(f.request),same=f.adapter.stop({...f.request});
  assert.equal((await f.adapter.stop({...f.request,commandId:randomUUID()})).code,'STOP_ALREADY_PENDING');
  await new Promise(setImmediate);finish({sdk_released:true});
  assert.deepEqual(await same,await first);assert.deepEqual(await f.adapter.stop(f.request),await first);
});

test('deadline timeout stays unknown after a late SDK result and cannot revive the settled request',async()=>{
  let finish;const f=fixture({releaseSdk:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=f.adapter.stop(f.request);await new Promise(setImmediate);f.advance(1100);f.timers[0].fn();
  const result=await pending;assert.equal(result.code,'STOP_RESPONSE_TIMEOUT');assert.equal(result.sdkReleased,false);
  finish({sdk_released:true,stopped:true});await new Promise(setImmediate);
  assert.deepEqual(await f.adapter.stop(f.request),result);
});

test('changed executor during SDK release discards its stale completion',async()=>{
  let finish;const f=fixture({releaseSdk:()=>new Promise(resolve=>{finish=resolve;})});
  const pending=f.adapter.stop(f.request);await new Promise(setImmediate);f.state.hardwareFingerprint='c'.repeat(64);finish({sdk_released:true});
  const result=await pending;assert.equal(result.code,'WRONG_EXECUTOR');assert.equal(result.state,'unknown');assert.equal(result.sdkReleased,false);
});

function nativeFixture(change=()=>{}){
  const profile={digest:'b'.repeat(64),stop:{maxStopTimeMs:1000,maxFeedbackAgeMs:200,maxVelocityRadS:0.01,
    maxJointDeltaDeg:0.2,minStableDurationMs:100,minSamples:3,requiresDisabled:false,includesGripper:false}};
  let f;const nativeCalls=[],feedbackCalls=[];
  f=fixture({nativeStopSupported:true,requestControlledStop:async request=>{nativeCalls.push(request);return {stopped:true};},
    readStopEvidence:async request=>{
      feedbackCalls.push(request);f.advance(300,10200);
      const evidence={commandId:request.commandId,executorEpoch:request.executorEpoch,hardwareFingerprint:request.hardwareFingerprint,
        requestedAt:request.requestedAt,observedAt:10200,state:'stopped',reason:'HARDWARE_FEEDBACK',
        measurement:{kind:'hardware_feedback',sourceMode:'hardware',profileDigest:profile.digest,jointVelocitiesRadS:[0,0,0,0,0,0],
          jointDeltaDeg:[0,0,0,0,0,0],sampleCount:3,stableDurationMs:150,driversDisabled:false}};
      change(evidence);return evidence;
    },stopProfile:profile});
  return {...f,nativeCalls,feedbackCalls};
}

test('configured native adapter verifies a newly measured feedback window using the local profile',async()=>{
  const f=nativeFixture();const result=await f.adapter.stop(f.request);
  assert.equal(result.state,'stopped');assert.equal(result.code,'HARDWARE_STOP_VERIFIED');assert.equal(result.depowered,false);
  assert.equal(f.nativeCalls.length,1);assert.equal(f.feedbackCalls.length,1);assert.equal(f.calls.length,0);
  assert.equal(f.adapter.capabilities().controlledStop,true);
});

test('native success boolean, cached/other-request evidence or wrong epoch cannot prove standstill',async()=>{
  for(const change of [e=>{e.requestedAt-=100;},e=>{e.commandId=randomUUID();},e=>{e.executorEpoch=randomUUID();},
    e=>{e.measurement.kind='sdk_cleanup';},e=>{e.measurement.sampleCount=1;},e=>{e.measurement.jointVelocitiesRadS=new Array(6);}]){
    const f=nativeFixture(change);assert.equal((await f.adapter.stop(f.request)).state,'unknown');
  }
});

test('setting capability true without explicit native callable/profile/feedback remains closed',async()=>{
  const f=fixture({nativeStopSupported:true,requestControlledStop:async()=>({stopped:true})});
  const result=await f.adapter.stop(f.request);assert.equal(result.code,'CONTROLLED_STOP_UNSUPPORTED');
  assert.equal(f.adapter.capabilities().controlledStop,false);assert.equal(f.calls.length,1);
});

test('arbitrary SDK errors are suppressed and never become stop evidence or returned text',async()=>{
  const f=fixture({releaseSdk:async()=>{throw Error('untrusted third party secret text');}});
  const result=await f.adapter.stop(f.request);assert.equal(result.state,'unknown');assert.equal(result.sdkReleased,false);
  assert.equal(JSON.stringify(result).includes('third party'),false);
});

test('the same request ID with another lease epoch never reuses a pending or completed stop',async()=>{
  const f=fixture();await f.adapter.stop(f.request);
  assert.equal((await f.adapter.stop({...f.request,leaseEpoch:2})).code,'STOP_REQUEST_CONFLICT');
  assert.equal((await f.adapter.stop({...f.request,leaseId:randomUUID()})).code,'STOP_REQUEST_CONFLICT');
  assert.equal(f.calls.length,1);
});

test('feedback validation crossing the monotonic deadline cannot confirm or retain evidence',async()=>{
  let f;
  f=nativeFixture(e=>{
    const measured=e.measurement;
    Object.defineProperty(e,'measurement',{get(){f.advance(1100,10200);return measured;}});
  });
  const result=await f.adapter.stop(f.request);
  assert.equal(result.state,'unknown');assert.equal(result.code,'STOP_RESPONSE_TIMEOUT');
  assert.equal(f.adapter.getEvidence(f.request),null);
});
