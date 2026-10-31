'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {StartouchBridge}=require('../../../services/robot/src/startouch-bridge');

function fixture(t,{ack=true}={}){
  const clock={now:1000000};t.mock.method(Date,'now',()=>clock.now);
  const bridge=new StartouchBridge({remoteLeaseGuard:true,simulate:true,canInterface:'can0'});
  const sent=[],errors=[];
  bridge.child={stdin:{writable:true,writableLength:0,write:value=>{sent.push(JSON.parse(value));return true;}}};
  bridge.on('bridge_error',value=>errors.push(value));bridge._scheduleRestart=()=>{};
  if(ack)bridge._handleLine(JSON.stringify({type:'bridge_ready',remote_lease_guard:true,remote_lease_protocol:'thirdhand-worker-lease-v1'}));
  const lease=Object.fromEntries(['deviceId','bootId','executorEpoch','connectionId','certificateId','leaseId'].map(key=>[key,randomUUID()]));
  Object.assign(lease,{hardwareFingerprint:'a'.repeat(64),leaseEpoch:1,sequence:0,issuedAt:1000000,expiresAt:1000950});
  return {bridge,clock,lease,sent,errors};
}

test('remote SDK commands fail closed until worker lease is queued and carry a copied original binding',t=>{
  const f=fixture(t);assert.equal(f.bridge.send({cmd:'connect'}),false);assert.equal(f.sent.length,0);
  assert.equal(f.bridge.armRemoteLease(f.lease),true);assert.equal(f.sent[0].cmd,'remote_lease_arm');
  assert.equal(f.bridge.send({cmd:'connect'}),true);assert.deepEqual(f.sent[1].remote_lease,f.lease);
  f.lease.expiresAt+=100000;assert.equal(f.sent[1].remote_lease.expiresAt,1000950);
});

test('guard transport preserves original absolute expiry and refuses late or backpressured renewals',t=>{
  const f=fixture(t);assert.equal(f.bridge.armRemoteLease(f.lease),true);
  f.clock.now+=400;
  const renew={...f.lease,sequence:1,issuedAt:1000400,expiresAt:1001350};
  assert.equal(f.bridge.renewRemoteLease(renew),true);assert.equal(f.sent[1].lease.expiresAt,1001350);
  f.bridge.child.stdin.writableLength=4;
  assert.equal(f.bridge.renewRemoteLease({...renew,sequence:2}),false);assert.equal(f.sent.length,2);
  f.bridge.child.stdin.writableLength=0;f.clock.now=1001350;
  assert.equal(f.bridge.renewRemoteLease({...renew,sequence:2}),false);assert.equal(f.sent.length,2);
  assert.equal(f.bridge.send({cmd:'gripper',position:0.5}),false);
});

test('same binding/sequence replay and a new epoch disguised as renewal are rejected',t=>{
  const f=fixture(t);f.bridge.armRemoteLease(f.lease);
  for(const change of [{...f.lease},{...f.lease,sequence:1,leaseEpoch:2},{...f.lease,sequence:1,connectionId:randomUUID()}])
    assert.equal(f.bridge.renewRemoteLease(change),false);
  assert.equal(f.sent.length,1);
});

test('revoke latches SDK command admission immediately and requires an explicit higher generation',t=>{
  const f=fixture(t);f.bridge.armRemoteLease(f.lease);
  assert.equal(f.bridge.revokeRemoteLease('agent_died'),true);
  assert.equal(f.sent[1].cmd,'remote_lease_revoke');assert.deepEqual(f.sent[1].lease,f.lease);
  assert.equal(f.bridge.send({cmd:'move_joint',joints_rad:[0,0,0,0,0,0]}),false);
  assert.equal(f.bridge.armRemoteLease(f.lease),false);
  assert.equal(f.bridge.armRemoteLease({...f.lease,leaseEpoch:2,leaseId:randomUUID()}),true);
});

test('worker exit discards the lease and does not silently arm the restarted worker',t=>{
  const f=fixture(t);f.bridge.armRemoteLease(f.lease);
  f.bridge._handleExit(f.bridge.child,1,null);
  f.bridge.child={stdin:{writable:true,write:()=>assert.fail('old lease must not be sent')}};
  assert.equal(f.bridge.send({cmd:'connect'}),false);assert.equal(f.bridge.getInfo().remoteLeaseGuard,true);
});

test('legacy local mode keeps unguarded command transport and never pretends remote guard is enabled',()=>{
  const bridge=new StartouchBridge({simulate:true}),sent=[];
  bridge.child={stdin:{writable:true,write:line=>{sent.push(JSON.parse(line));return true;}}};
  assert.equal(bridge.send({cmd:'connect'}),true);assert.deepEqual(sent,[{cmd:'connect'}]);
  assert.equal(bridge.armRemoteLease({}),false);assert.equal(bridge.getInfo().remoteLeaseGuard,false);
});

test('an old or mismatched worker cannot arm a lease merely because Node configuration enables it',t=>{
  const f=fixture(t,{ack:false});
  assert.equal(f.bridge.armRemoteLease(f.lease),false);
  f.bridge._handleLine(JSON.stringify({type:'bridge_ready'}));assert.equal(f.bridge.armRemoteLease(f.lease),false);
  f.bridge._handleLine(JSON.stringify({type:'bridge_ready',remote_lease_guard:true,remote_lease_protocol:'wrong'}));
  assert.equal(f.bridge.armRemoteLease(f.lease),false);assert.equal(f.sent.length,0);
});

test('worker lease status and expiry reach the controller source audit unchanged',()=>{
  const {RobotController}=require('../../../services/robot/src/robot-controller');
  const controller=new RobotController({simulate:true});const messages=[];
  controller.on('message',value=>messages.push(value));
  for(const type of ['remote_lease_status','remote_lease_expired']){
    const value={type,binding:{leaseId:randomUUID()},active:false,stop_state:'unknown'};
    controller._handleBridgeMessage(value);assert.equal(messages.at(-1),value);
  }
});

test('a real simulated Python worker cancels while its Node parent event loop is paused',async()=>{
  const bridge=new StartouchBridge({simulate:true,remoteLeaseGuard:true,python:process.env.PYTHON||'python3',sdkPath:__dirname,
    modulePath:'',canInterface:'can0',gripper:false,requireCanRx:false,canRxStaleSec:1,pollIntervalMs:50,
    jointLogIntervalMs:1000,initSettleSec:0,initSampleCount:2,initMaxDriftDeg:2,speedScale:0.05});
  const messages=[];bridge.on('message',message=>messages.push(message));
  function wait(predicate){
    const existing=messages.find(predicate);if(existing)return Promise.resolve(existing);
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{bridge.off('message',receive);reject(Error('simulated worker event timeout'));},5000);
      function receive(message){if(predicate(message)){clearTimeout(timer);bridge.off('message',receive);resolve(message);}}
      bridge.on('message',receive);
    });
  }
  try{
    bridge.start();await wait(message=>message.type==='bridge_ready');
    const now=Date.now(),lease=Object.fromEntries(['deviceId','bootId','executorEpoch','connectionId','certificateId','leaseId'].map(key=>[key,randomUUID()]));
    Object.assign(lease,{hardwareFingerprint:'a'.repeat(64),leaseEpoch:1,sequence:0,issuedAt:now,expiresAt:now+950});
    assert.equal(bridge.armRemoteLease(lease),true);
    await wait(message=>message.type==='remote_lease_status'&&message.active);
    assert.equal(bridge.send({cmd:'connect'}),true);
    await wait(message=>message.type==='connection'&&message.connected);
    const expired=wait(message=>message.type==='remote_lease_expired');
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,1400);
    const resumedAt=Date.now(),event=await expired;
    assert.equal(event.stop_state,'unknown');
    assert.ok(event.ts<resumedAt-100,'worker cleanup should have finished while Node could not run callbacks');
    const released=messages.find(message=>message.type==='connection'&&message.reason==='remote_lease_expired');
    assert.equal(released.sdk_released,true);assert.equal(released.stop_state,'unknown');
  }finally{
    const child=bridge.child;
    const exited=child?new Promise(resolve=>child.once('exit',resolve)):Promise.resolve();
    bridge.shutdown();await exited;
  }
});
