'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {buildGraspGeometry,getGripPosition,validateJoints,validateConfig}=require('../../../apps/web/src/grasp/geometry');
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
test('shipped horizontal profile advances to the measured-TCP checkpoint instead of retreating into the folded workspace',()=>{
 const f=fixture(),profile=require('../../../apps/web/configs/web-grasp.json');
 f.config={...profile,framePolicyId:policy,calibrationId:calibration,forwardBackoffM:0,
  T_flange_grasp_tcp:[[1,0,0,.09826448704090089],[0,1,0,-.006341722837237676],[0,0,1,-.0013153436560723233],[0,0,0,1]]};
 f.robot={flange_position_m:[.2888374153738635,-.005301108903154579,.1741254892574079],
  flange_euler_rad:[-.002014569514826276,.016148429639032333,-.046170187386362915],
  joints_deg:[2.458905621126779,-9.453126054554062,-.7759213293333391,11.157967285201961,-5.1035952225164705,-.03278540828169039]};
 f.observation.frame_projection.T_base_camera=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
 const target=[.375536122637,-.001544095485,.20682912268];
 Object.assign(f.observation.targets[0],{camera_xyz_m:target,base_xyz_m:target});
 const g=buildGraspGeometry(f);
 assert.ok(g.paths.preapproach.every(p=>p.position[0]>f.robot.flange_position_m[0]),'preapproach must not retreat into the failed near-base IK region');
 assert.ok(Math.abs(g.preapproach.position[0]-.350930890987)<1e-9);
 assert.ok(Math.abs(g.contact.position[0]-.450824325609)<1e-9);
 assert.equal(g.preapproach.position[2],.174125489257);
 assert.ok(Object.values(g.paths).flat().every(p=>p.euler[0]===0&&p.euler[1]===0));
});
test('horizontal grasp keeps roll and pitch level and preserves horizontal heading',()=>{
 const f=fixture();f.config.orientationMode='horizontal';f.config.horizontalToleranceRad=.05;
 f.robot.flange_euler_rad=[.01,-.02,Math.PI/2];
 const g=buildGraspGeometry(f);
 for(const waypoint of [g.preapproach,g.contact,g.lift]){assert.equal(waypoint.euler[0],0);assert.equal(waypoint.euler[1],0);assert.ok(Math.abs(waypoint.euler[2]-Math.PI/2)<1e-11);}
 assert.equal(g.contact.gripM[2],.2);assert.equal(g.contact.position[2],.2);
});
test('horizontal grasp rejects an initially pitched tool before planning a leveling sweep',()=>{
 const f=fixture();f.config.orientationMode='horizontal';f.config.horizontalToleranceRad=.05;
 f.robot.flange_euler_rad=[0,.49,0];
 assert.throws(()=>buildGraspGeometry(f),/tool_not_horizontal/);
});
test('horizontal heading stays frozen across target refresh instead of following yaw drift',()=>{
 const f=fixture();f.config.orientationMode='horizontal';f.config.horizontalYawRad=.2;
 f.robot.flange_euler_rad=[0,0,.22];
 assert.ok(Math.abs(buildGraspGeometry(f).contact.euler[2]-.2)<1e-11);
});
test('motion modes and their bounds cannot silently fall back on malformed configuration',()=>{
 for(const override of [{orientationMode:'horzontal'},{executionMode:'phase-linar'},
  {orientationMode:'horizontal',horizontalToleranceRad:.5},{depthTimeoutMs:0},{horizontalYawRad:NaN}]){
  assert.throws(()=>validateConfig({...fixture().config,...override}),/grasp_config_invalid/);
 }
});
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
test('operator forward overshoot compensation backs contact off 60mm without changing height or calibration',()=>{
 const f=fixture();f.config.forwardBackoffM=0.06;
 const g=buildGraspGeometry(f);
 assert.deepEqual(g.targetM,[0.4,0,0.2]);
 assert.deepEqual(g.contact.gripM,[0.34,0,0.2]);
 assert.deepEqual(g.contact.flangeM,[0.28,0,0.2]);
 assert.deepEqual(g.contact.position,[0.45334,0,0.2]);
 assert.deepEqual(g.preapproach.position,[0.41334,0,0.2]);
 assert.deepEqual(g.lift.position,[0.45334,0,0.25]);
 const repeated=buildGraspGeometry(f);assert.deepEqual(repeated.contact,g.contact);
 assert.equal(f.config.gripOffsetM,0.06);
});
test('forward backoff follows horizontal wrist forward direction while preserving pitched contact Z',()=>{
 const f=fixture();f.config.forwardBackoffM=0.06;f.robot.flange_euler_rad=[0,Math.PI/6,Math.PI/2];
 const g=buildGraspGeometry(f);
 assert.ok(Math.abs(g.contact.gripM[0]-0.4)<1e-12);
 assert.ok(Math.abs(g.contact.gripM[1]+0.06)<1e-12);
 assert.equal(g.contact.gripM[2],0.2);
 assert.ok(Math.abs(g.contact.position[2]-0.14333)<1e-12);
 assert.ok(Math.abs(g.contact.position[1]-0.038154)+0<1e-5);
});
test('invalid forward compensation or vertical ambiguous forward axis rejects planning',()=>{
 for(const value of [-0.01,NaN,0.101]){const f=fixture();f.config.forwardBackoffM=value;assert.throws(()=>buildGraspGeometry(f),/grasp_config_invalid/);}
 const f=fixture();f.config.forwardBackoffM=0.06;f.robot.flange_euler_rad=[0,Math.PI/2,0];
 assert.throws(()=>buildGraspGeometry(f),/forward_axis_invalid/);
});
test('forward contact correction does not shift the visibility checkpoint toward the base',()=>{
 const f=fixture();f.config.preapproachM=0.2;f.config.keepPreapproachSdkHeight=true;f.config.forwardBackoffM=0.06;
 const g=buildGraspGeometry(f);
 assert.deepEqual(g.preapproach.position,[0.31334,0,0.2]);
 assert.deepEqual(g.preapproach.gripM,[0.2,0,0.2]);
 assert.deepEqual(g.contact.position,[0.45334,0,0.2]);
 assert.deepEqual(g.paths.approach.at(-1).position,[0.45334,0,0.2]);
});
