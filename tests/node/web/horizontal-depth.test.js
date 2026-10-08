'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {fixture}=require('./grasp-geometry.test');
let implementation;try{implementation=require('../../../apps/web/src/active-depth/horizontal');}catch(e){if(e.code!=='MODULE_NOT_FOUND')throw e;}
const camera={matrix_4x4:[[0,0,1,0],[-1,0,0,0],[0,-1,0,0],[0,0,0,1]],camera_mount_id:'mount',registration_id:'reg'};
function data(pixel=[420,234],valid=false){const f=fixture();return {robot:{...f.robot,jointsDeg:f.robot.joints_deg},
 startRobot:structuredClone({...f.robot,jointsDeg:f.robot.joints_deg}),targetPixel:pixel,depthValid:valid,mount:camera,
 config:{...f.config,orientationMode:'horizontal',horizontalToleranceRad:.05,maxIkStepDeg:5}};}
function plan(d){assert.equal(typeof implementation?.planHorizontalDepthStep,'function','horizontal depth acquisition must have a real planner');return implementation.planHorizontalDepthStep(d);}
test('off-center target produces a horizontal waypoint without inventing a target distance',()=>{
 const p=plan(data());assert.equal(p.ok,true,p.reason);assert.equal(p.tier,'horizontal');
 assert.equal(p.targetSdkPose.euler[0],0);assert.equal(p.targetSdkPose.euler[1],0);
 assert.ok(p.cameraShiftM<=.01);assert.ok(Math.abs(p.targetSdkPose.euler[2])<=Math.PI/180+.00001);
 assert.equal(p.camera_xyz_m,undefined);
});
test('centered missing depth requests a bounded backward move with unchanged attitude',()=>{
 const p=plan(data([315.5,234]));assert.equal(p.ok,true,p.reason);assert.equal(p.adjustment,'backoff');
 assert.deepEqual(p.targetSdkPose.euler,[0,0,0]);
 assert.ok(p.targetSdkPose.position[0]<data().robot.flange_position_m[0]);
 assert.ok(p.cameraShiftM<=.005001);
});
test('pitch and exhausted camera travel prohibit a depth motion',()=>{
 const pitched=data();pitched.robot.flange_euler_rad=[0,.2,0];assert.equal(plan(pitched).ok,false);
 const exhausted=data([315.5,234]);exhausted.robot.flange_position_m[0]-=.04;
 assert.equal(plan(exhausted).ok,false);
});
test('standalone horizontal depth prepares the web client, collects three frames and sends no motion when depth is already valid',async()=>{
 assert.equal(typeof implementation?.HorizontalDepthCoordinator,'function');
 const d=data([315.5,234],true);let frame=0,prepared=0,motion=0;
 const robot={ready:async()=>{prepared++;},state:()=>({...d.robot,connected:true,stateFresh:true,stateName:'IDLE',motionActive:false}),
  command:async()=>{motion++;throw Error('no motion expected');},preview:async()=>({joints_deg:d.robot.joints_deg}),stop:async()=>({status:'interrupted'})};
 const vision={snapshot:async()=>({observation:{frameId:++frame,observedAtMs:Date.now(),selectedStableId:2,
  evidence_id:'sha256:'+'a'.repeat(64),frame_projection:{status:'ready',robot_frame_policy_id:d.config.framePolicyId,calibration_id:d.config.calibrationId},targets:[{stable_id:2,track_state:'confirmed',centroid_xy:[315.5,234],depth_valid:true,camera_xyz_m:[0,0,.4]}]},
  runtimeEvidence:{camera_mount_id:'mount',registration_id:'reg'}})};
 const c=new implementation.HorizontalDepthCoordinator({robotClient:robot,visionClient:vision,mount:camera,getConfig:()=>d.config,pollIntervalMs:0});
 await c.start(2);for(let i=0;i<100&&c.status().active;i++)await new Promise(r=>setImmediate(r));
 assert.equal(c.status().phase,'depth_acquired',c.status().reason);assert.equal(prepared,1);assert.equal(motion,0);
 await c.close();
});
function movingHarness({fault=false,stale=false,transient=false,buffered=false,monotonic=false}={}){
 const d=data();let sequence=1,frame=0,moved=false,stops=0,allowStop=!fault;
 const sent=[];let bufferedSeen=0,releaseFrames=false;const oldStamp=Date.now()-100;
 const robot={ready:async()=>{},state:()=>({...d.robot,jointsDeg:d.robot.joints_deg,state_sequence:++sequence,connected:true,stateFresh:true,stateName:'IDLE',motionActive:false,...(monotonic?{producer_monotonic_ns:2000000}:{})}),
  preview:async()=>({joints_deg:[0,0,-1,0,0,0]}),command:async p=>{sent.push(p);if(fault)throw Object.assign(Error('feedback_stale'),{code:'feedback_stale',motionUncertain:true});
   d.robot.flange_position_m=p.position;d.robot.flange_euler_rad=p.euler;moved=true;return {reached:true};},
  stop:async()=>{stops++;if(!allowStop)throw Error('stop_unconfirmed');return {status:'interrupted'};}};
 let transientSeen=false;
 const vision={snapshot:async()=>{if(moved&&transient&&!transientSeen){transientSeen=true;throw Object.assign(Error('updating'),{code:'vision_target_mismatch'});}
  if(moved&&buffered&&!releaseFrames)bufferedSeen++;
  return {observation:{frameId:++frame,observedAtMs:stale?Date.now()-10000:(moved&&buffered&&!releaseFrames&&!monotonic?oldStamp:Date.now()),selectedStableId:2,evidence_id:'sha256:'+'a'.repeat(64),
   frame_projection:{status:'ready',robot_frame_policy_id:d.config.framePolicyId,calibration_id:d.config.calibrationId,
    ...(monotonic?{frame_monotonic_ns:moved&&buffered&&!releaseFrames?1000000:3000000,robot_observed_monotonic_ns:moved&&buffered&&!releaseFrames?1000000:3000000}:{})},
   targets:[{stable_id:2,track_state:'confirmed',centroid_xy:moved?[315.5,234]:[420,234],depth_valid:moved,camera_xyz_m:moved?[0,0,.4]:null}]},
   runtimeEvidence:{camera_mount_id:'mount',registration_id:'reg'}};}};
 const c=new implementation.HorizontalDepthCoordinator({robotClient:robot,visionClient:vision,mount:camera,getConfig:()=>d.config,pollIntervalMs:0});
 return {c,sent,get stops(){return stops;},allowStop:()=>allowStop=true,get bufferedSeen(){return bufferedSeen;},releaseFrames:()=>releaseFrames=true};
}
async function terminal(c){for(let i=0;i<1000&&!['failed','uncertain','depth_acquired'].includes(c.status().phase);i++)await new Promise(r=>setImmediate(r));return c.status();}
test('horizontal motion stays level through web move_l and tolerates one post-motion redetection frame',async()=>{
 const h=movingHarness({transient:true});await h.c.start(2);const s=await terminal(h.c);
 assert.equal(s.phase,'depth_acquired',s.reason);assert.equal(h.sent.length,1);assert.equal(h.sent[0].cmd,'move_l');
 assert.equal(h.sent[0].euler[0],0);assert.equal(h.sent[0].euler[1],0);await h.c.close();
});
test('stale vision prohibits a depth movement',async()=>{
 const h=movingHarness({stale:true});await h.c.start(2);const s=await terminal(h.c);
 assert.equal(s.reason,'vision_stale');assert.equal(h.sent.length,0);await h.c.close();
});
test('unconfirmed horizontal motion stop retains ownership until an explicit retry confirms stopping',async()=>{
 const h=movingHarness({fault:true});await h.c.start(2);const s=await terminal(h.c);
 assert.equal(s.phase,'uncertain',s.reason);assert.equal(h.stops,1);assert.equal(s.active,true);
 await assert.rejects(h.c.start(2));h.allowStop();await h.c.stop(s.sessionId);
 assert.equal(h.c.status().phase,'stopped');assert.equal(h.c.status().active,false);await h.c.close();
});
test('closing uncertain depth retries a stop before releasing the transport',async()=>{
 const h=movingHarness({fault:true});await h.c.start(2);await terminal(h.c);
 h.allowStop();await h.c.close();assert.equal(h.stops,2);
 assert.equal(h.c.status().phase,'stopped');assert.equal(h.c.status().active,false);
});
test('higher-numbered buffered pre-motion frames cannot qualify depth or issue another correction',async()=>{
 const h=movingHarness({buffered:true});await h.c.start(2);
 for(let i=0;i<1000&&h.bufferedSeen<4;i++)await new Promise(r=>setImmediate(r));
 assert.ok(h.bufferedSeen>=4);assert.equal(h.c.status().active,true);assert.equal(h.c.status().depthValidFrames,0);assert.equal(h.sent.length,1);
 h.releaseFrames();assert.equal((await terminal(h.c)).phase,'depth_acquired');await h.c.close();
});
test('fresh publication timestamps cannot hide capture and projection evidence from before motion',async()=>{
 const h=movingHarness({buffered:true,monotonic:true});await h.c.start(2);
 for(let i=0;i<1000&&h.bufferedSeen<4;i++)await new Promise(r=>setImmediate(r));
 assert.ok(h.bufferedSeen>=4);assert.equal(h.c.status().active,true);assert.equal(h.c.status().depthValidFrames,0);assert.equal(h.sent.length,1);
 h.releaseFrames();assert.equal((await terminal(h.c)).phase,'depth_acquired');await h.c.close();
});
test('close refuses to tear down an unresolved uncertain session',async()=>{
 const h=movingHarness({fault:true});await h.c.start(2);await terminal(h.c);
 await assert.rejects(h.c.close(),e=>e.code==='stop_unconfirmed');assert.equal(h.stops,2);assert.equal(h.c.status().active,true);
 h.allowStop();await h.c.close();assert.equal(h.c.status().active,false);
});
