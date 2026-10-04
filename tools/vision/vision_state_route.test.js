'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {once,EventEmitter}=require('node:events');
const {WebSocket}=require('ws');
const {createVisionService}=require(process.env.VISION_STATE_ENTRY);
test('Vision WebSocket passes arm telemetry to its camera pipeline without robot control',async t=>{
  const camera=new EventEmitter();
  let received=null;
  let cameraReady=false;
  camera.start=()=>{};camera.close=async()=>{};
  camera.status=()=>({camera:{status:cameraReady?'ready':'starting'},inference:{status:'ready'}});
  camera.send=message=>{received=message;return true;};
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'vision-state-route-test-'));
  const service=createVisionService({camera,host:'127.0.0.1',port:0,meituanPort:null,
    readyFile:path.join(directory,'ready')});
  const address=await service.start();
  const client=new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(async()=>{client.terminate();await service.close();fs.rmdirSync(directory);});
  await once(client,'open');
  const state={type:'arm_state',pose_frame:'robot_flange',connected:true,healthy:true,
    stationary:true,flange_position_m:[0.3,0,0.18],flange_euler_rad:[0,0,0],
    joints_deg:[0,0,0,0,0,0],observed_monotonic_ns:100};
  client.send(JSON.stringify(state));
  await new Promise(r=>setTimeout(r,30));
  assert.equal(received,null,'telemetry must not write to a starting camera pipe');
  cameraReady=true;
  client.send(JSON.stringify(state));
  for(let n=0;n<30&&!received;n++)await new Promise(r=>setTimeout(r,10));
  assert.deepEqual(received,state);
  const health=await(await fetch(`http://127.0.0.1:${address.port}/health`)).json();
  assert.equal(health.robotControlEnabled,false);
});
