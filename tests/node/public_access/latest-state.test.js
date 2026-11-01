'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createLatestState}=require('../../../services/device-relay/src/latest-state');
const {createDeviceStateStore}=require('../../../apps/web/public/js/device-state');
function fixture(){
 let wall=1793500000000,mono=0,context={deviceId:'device',bootId:'boot',executorEpoch:'executor',connectionId:'connection',certificateId:'certificate'};
 const cache=createLatestState({contextFor:()=>context,wallNow:()=>wall,monoNow:()=>mono});
 const report=()=>({schema:1,purpose:'latest_state',context:{...context},sequence:1,producerMonotonicNs:1000,sourceAgeMs:20,issuedAt:wall-50,sample:{capturedAt:new Date(wall-80).toISOString(),clockQuality:'estimated',jointPositionRad:[0,1,2,3,4,5],gripper:{positionRatio:0.5,widthM:0.025},sdkConnected:true,moving:false,fieldAvailability:{sdkConnected:true,moving:true},extra:{sourceMode:'hardware',rawState:{secret:'never transmit'},target:{jointPositionRad:[9,9,9,9,9,9]},flangePositionM:[.1,.2,.3]}}});
 return {cache,report,get context(){return context;},advance(ms){mono+=ms;wall+=ms;},wallJump(ms){wall+=ms;},replace(){context={...context,connectionId:'new',bootId:'new-boot'};},disconnect(){context=null;}};
}
test('live state uses measurements and nullable fields, not targets or inferred gripper width',()=>{
 const f=fixture();f.cache.accept(f.context,f.report());const s=f.cache.get('device');assert.equal(s.fresh,true);assert.equal(s.ageMs,80);assert.equal(s.sample.gripper.widthM,.025);assert.equal(s.sample.jointCurrentA,null);assert.equal(s.sample.tcpPositionM,null);assert.deepEqual(s.sample.flangePositionM,[.1,.2,.3]);assert.equal(JSON.stringify(s).includes('secret'),false);assert.equal(JSON.stringify(s).includes('target'),false);
});
test('repeat, backward sequence, delayed frame, future timestamp and forged context cannot refresh state',()=>{
 const f=fixture(),original=f.report();f.cache.accept(f.context,original);f.advance(1000);
 for(const update of [{},{sequence:0},{sequence:2,producerMonotonicNs:999},{sequence:2,producerMonotonicNs:2000,sourceAgeMs:3001},{context:{...f.context,bootId:'old'}},{issuedAt:original.issuedAt+2000},{sample:{...original.sample,capturedAt:'2099-01-01T00:00:00Z'}}])assert.throws(()=>f.cache.accept(f.context,{...original,...update}));
 assert.equal(f.cache.get('device').ageMs,1080);f.advance(2000);assert.equal(f.cache.get('device').fresh,false);
});
test('wall-clock rollback does not renew a sample and reconnect invalidates old epoch immediately',()=>{
 const f=fixture();f.cache.accept(f.context,f.report());f.advance(4000);f.wallJump(-100000);assert.equal(f.cache.get('device').fresh,false);f.replace();assert.equal(f.cache.get('device').epochCurrent,false);f.disconnect();assert.equal(f.cache.get('device').gatewayOnline,false);
});
function browser(){let mono=0,next,requests=0,pending=null;const scheduled=[],ticks=[],doc={visibilityState:'visible',addEventListener(){},removeEventListener(){}};
 const view={performance:{now:()=>mono},setInterval(fn){ticks.push(fn);return 1;},clearInterval(){},setTimeout(fn,ms){scheduled.push({fn,ms});return scheduled.length;},clearTimeout(){}};
 const store=createDeviceStateStore({view,document:doc,request:async path=>{requests++;if(path==='/api/v1/devices')return {devices:[{id:'device',controllable:true}]};return pending?pending:structuredClone(next);}});
 const f=fixture();f.cache.accept(f.context,f.report());next=f.cache.get('device');
 return {store,doc,scheduled,ticks,advance(ms){mono+=ms;},set(value){next=value;},pending(p){pending=p;},get requests(){return requests;}};
}
test('browser ages independently of polling, repeats do not renew, API failure retains last measured values',async()=>{
 const b=browser();await b.store.start();assert.equal(b.store.snapshot().status,'connected');b.advance(4000);assert.equal(b.store.snapshot().status,'stale');await b.store.refresh();assert.equal(b.store.snapshot().status,'stale');b.set({invalid:true});await b.store.refresh();assert.equal(b.store.snapshot().status,'read_failed');assert.deepEqual(b.store.snapshot().sample.jointPositionRad,[0,1,2,3,4,5]);assert.equal(b.scheduled.at(-1).ms,2000);b.store.close();
});
test('one in-flight read, background pause, bounded backoff and explicit connection phase',async()=>{
 const b=browser();await b.store.start();let resolve;b.pending(new Promise(r=>{resolve=r;}));const poll=b.store.refresh(),before=b.requests;await b.store.refresh();assert.equal(b.requests,before);b.advance(5000);assert.equal(b.store.snapshot().status,'stale');resolve({bad:true});await poll;for(let i=0;i<4;i++){b.pending(null);b.set({bad:true});await b.store.refresh();}assert.equal(b.scheduled.at(-1).ms,8000);b.doc.visibilityState='hidden';const paused=b.requests;await b.store.refresh();assert.equal(b.requests,paused);b.store.close();
});

test('connection completion clears pending UI without inventing a connected or stopped robot',async()=>{
 const b=browser();await b.store.start();const attempt=b.store.connecting();assert.equal(b.store.snapshot().status,'connecting');assert.equal(b.store.snapshot().sample,null);
 b.store.connectionSettled(attempt);assert.equal(b.store.snapshot().status,'unknown');assert.equal(b.store.snapshot().sample,null);
 const older=b.store.connecting(),current=b.store.connecting();b.store.connectionSettled(older);assert.equal(b.store.snapshot().status,'connecting');
 b.store.connectionSettled(current);assert.equal(b.store.snapshot().status,'unknown');b.store.close();
});

test('pending SDK UI is bounded and authoritative measurements win over command completion',async()=>{
 const b=browser();await b.store.start();b.store.connecting();b.advance(15001);assert.equal(b.store.snapshot().status,'unknown');
 const attempt=b.store.connecting();await b.store.refresh();assert.equal(b.store.snapshot().status,'connected');
 b.store.connectionSettled(attempt);assert.equal(b.store.snapshot().status,'connected');b.advance(3001);assert.equal(b.store.snapshot().status,'stale');b.store.close();
});
