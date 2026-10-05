'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {buildGraspGeometry,getGripPosition,validateJoints}=require('../../../apps/web/src/grasp/geometry');
const policy='sha256:'+ 'a'.repeat(64), calibration='sha256:'+'b'.repeat(64);
function fixture(){return {
 config:{gripOffsetM:0.060,sdkToolOffsetM:0.17334,preapproachM:0.100,liftM:0.050,segmentM:0.005,
  framePolicyId:policy,calibrationId:calibration,visionMaxAgeMs:2000,
  workspace:{x:[0.05,0.66],y:[-0.65,0.45],z:[0.04,0.65]},
  jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]]},
 robot:{flange_position_m:[0.30,0,0.20],flange_euler_rad:[0,0,0],joints_deg:[0,0,-1,0,0,0]},
 observation:{ts:1000,selectedStableId:2,frame_id:4,
  frame_projection:{status:'ready',robot_frame_policy_id:policy,calibration_id:calibration,
   T_base_camera:[[1,0,0,0.2],[0,1,0,0],[0,0,1,0],[0,0,0,1]],physically_validated:false},
  targets:[{stable_id:2,track_state:'confirmed',depth_valid:true,camera_xyz_m:[0.2,0,0.2],base_xyz_m:[0.4,0,0.2]}],
  pose:{width_m:0.03}},stableId:2,now:1000};}
test('60mm grip and SDK transforms are applied once without center advance',()=>{
 const p=buildGraspGeometry(fixture());
 assert.deepEqual(p.targetM,[0.4,0,0.2]);
 assert.deepEqual(p.contact.flangeM,[0.34,0,0.2]);
 assert.deepEqual(p.contact.position,[0.51334,0,0.2]);
 assert.deepEqual(p.preapproach.position,[0.41334,0,0.2]);
 assert.deepEqual(p.lift.position,[0.51334,0,0.25]);
 assert.deepEqual(getGripPosition(fixture().robot,fixture().config),[0.18666,0,0.2]);
});
test('60mm offset rotates with wrist rather than remaining in base X',()=>{
 const f=fixture();f.robot.flange_euler_rad=[0,0,Math.PI/2];
 const p=buildGraspGeometry(f);
 assert.ok(Math.abs(p.contact.flangeM[1]+0.06)<1e-12);
 assert.ok(Math.abs(p.contact.position[1]-0.11334)<1e-12);
 assert.ok(Math.abs(p.contact.position[0]-0.4)<1e-12);
});
test('all segments are bounded and reach literal contact/lift targets',()=>{
 const p=buildGraspGeometry(fixture());let previous=[0.3,0,0.2];
 for(const phase of ['preapproach','approach','lift'])for(const s of p.paths[phase]){
  assert.ok(Math.hypot(...s.position.map((x,i)=>x-previous[i]))<=0.0050000001);previous=s.position;}
 assert.deepEqual(previous,[0.51334,0,0.25]);
});
test('unapproved numerical projection stays usable but mismatched frames do not',()=>{
 assert.doesNotThrow(()=>buildGraspGeometry(fixture()));
 for(const field of ['robot_frame_policy_id','calibration_id']){const f=fixture();f.observation.frame_projection[field]='wrong';assert.throws(()=>buildGraspGeometry(f),/frame_binding_mismatch/);}
});
test('stale lost malformed depth and corrupt rigid projection are rejected',()=>{
 const cases=[f=>f.now=4000,f=>f.observation.selectedStableId=1,f=>f.observation.targets[0].depth_valid=false,
  f=>f.observation.targets[0].camera_xyz_m[0]=NaN,f=>f.observation.frame_projection.T_base_camera[0][0]=2,
  f=>f.observation.targets[0].base_xyz_m=[0,0,0]];
 for(const change of cases){const f=fixture();change(f);assert.throws(()=>buildGraspGeometry(f));}
});
test('invalid joint solutions cannot silently pass hard physical limits',()=>{
 const limits=fixture().config.jointLimits;
 assert.equal(validateJoints([0,0,-1,0,0,0],limits),true);
 for(const q of [[0,0,1,0,0,0],[0,0,NaN,0,0,0],[0,0,-1]])assert.equal(validateJoints(q,limits),false);
});
module.exports={fixture};
test('farther preapproach preserves current SDK height for eye-in-hand visibility',()=>{
 const f=fixture();f.config.preapproachM=0.18;f.config.keepPreapproachSdkHeight=true;f.robot.flange_position_m[2]=0.15;
 const g=buildGraspGeometry(f);
 assert.deepEqual(g.preapproach.position,[0.33334,0,0.15]);
 assert.deepEqual(g.preapproach.gripM,[0.22,0,0.15]);
 assert.deepEqual(g.contact.position,[0.51334,0,0.2]);
 assert.ok(g.paths.preapproach.every(p=>p.position[2]===0.15));
 const distance=Math.hypot(...g.contact.position.map((x,i)=>x-g.preapproach.position[i]));assert.ok(distance<0.22);
});
test('valid target depth stays usable when legacy bottle-plane qualification withholds pose width',()=>{
 const f=fixture();f.observation.pose=null;f.observation.reasons=['table_plane_ransac_failed'];
 const g=buildGraspGeometry(f);assert.deepEqual(g.targetM,[0.4,0,0.2]);assert.equal(g.widthM,null);
});
