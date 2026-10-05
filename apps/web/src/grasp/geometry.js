'use strict';
const {validateRigidTransform,gripTargetToFlangePose,flangeToGripPose}=require('../../../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');
const vector=(v,n=3)=>Array.isArray(v)&&v.length===n&&Array.from(v).every(Number.isFinite);
const rounded=x=>Number(x.toFixed(12));
function fail(code){const e=new Error(code);e.code=code;throw e;}
function translation(x){return [[1,0,0,x],[0,1,0,0],[0,0,1,0],[0,0,0,1]];}
function validateJoints(q,limits){return vector(q,6)&&Array.isArray(limits)&&limits.length===6&&q.every((x,i)=>vector(limits[i],2)&&x>=limits[i][0]&&x<=limits[i][1]);}
function validateConfig(c){
 for(const k of ['gripOffsetM','sdkToolOffsetM','preapproachM','liftM','segmentM','visionMaxAgeMs'])if(!Number.isFinite(c?.[k])||c[k]<=0)fail('grasp_config_invalid');
 if(c.segmentM>0.005||c.gripOffsetM>0.3||c.sdkToolOffsetM>0.3||c.preapproachM>0.2||c.liftM>0.1)fail('grasp_config_invalid');
 if(c.maxApproachM!==undefined&&(!Number.isFinite(c.maxApproachM)||c.maxApproachM<c.preapproachM||c.maxApproachM>0.25))fail('grasp_config_invalid');
 for(const k of ['framePolicyId','calibrationId'])if(!/^sha256:[a-f0-9]{64}$/.test(c[k]))fail('grasp_config_invalid');
 for(const k of ['x','y','z'])if(!vector(c.workspace?.[k],2)||c.workspace[k][0]>=c.workspace[k][1])fail('grasp_config_invalid');
 if(!Array.isArray(c.jointLimits)||c.jointLimits.length!==6||c.jointLimits.some(x=>!vector(x,2)||x[0]>=x[1]))fail('grasp_config_invalid');
 if(c.legacyGraspEnabled===true)fail('legacy_grasp_must_stay_disabled');return c;
}
function inside(p,c){return vector(p)&&['x','y','z'].every((axis,i)=>p[i]>=c.workspace[axis][0]&&p[i]<=c.workspace[axis][1]);}
function getGripPosition(robot,config){
 if(!vector(robot?.flange_position_m)||!vector(robot?.flange_euler_rad))fail('robot_pose_invalid');
 return gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM-config.gripOffsetM)).positionM.map(rounded);
}
function segments(from,to,config){
 const distance=Math.hypot(...to.position.map((x,i)=>x-from[i]));const count=Math.max(1,Math.ceil(distance/config.segmentM));
 if(count>200)fail('path_too_long');
 return Array.from({length:count},(_,i)=>({position:from.map((x,j)=>rounded(x+(to.position[j]-x)*(i+1)/count)),euler:[...to.euler]}));
}
function buildGraspGeometry({observation,stableId,robot,config,now=Date.now()}){
 validateConfig(config);
 const observed=Number(observation?.observedAtMs??observation?.ts);
 if(!Number.isFinite(observed)||now-observed>config.visionMaxAgeMs||observed-now>500)fail('vision_stale');
 if(Number(observation?.selectedStableId??observation?.selected_stable_id)!==stableId)fail('target_switched');
 const matches=(observation.targets||[]).filter(t=>Number(t.stable_id??t.stableId)===stableId);
 if(matches.length!==1||matches[0].track_state!=='confirmed')fail('target_lost');
 const target=matches[0],p=observation.frame_projection;
 if(target.depth_valid!==true||!vector(target.camera_xyz_m))fail('depth_invalid');
 if(p?.status!=='ready'||p.robot_frame_policy_id!==config.framePolicyId||p.calibration_id!==config.calibrationId)fail('frame_binding_mismatch');
 const m=validateRigidTransform(p.T_base_camera);
 const targetM=m.slice(0,3).map(row=>rounded(row[3]+row.slice(0,3).reduce((sum,x,j)=>sum+x*target.camera_xyz_m[j],0)));
 if(!vector(target.base_xyz_m)||Math.hypot(...target.base_xyz_m.map((x,i)=>x-targetM[i]))>0.0001)fail('base_point_corrupt');
 if(!vector(robot?.flange_position_m)||!vector(robot?.flange_euler_rad)||!validateJoints(robot.joints_deg,config.jointLimits))fail('robot_pose_invalid');
 const widthM=observation.pose?.width_m;
 if(!Number.isFinite(widthM)||widthM<0.008||widthM>0.072)fail('bottle_width_invalid');
 const desired={positionM:targetM,eulerRad:[...robot.flange_euler_rad]};
 const flange=gripTargetToFlangePose(desired,translation(config.gripOffsetM));
 const sdk=flangeToGripPose(flange,translation(config.sdkToolOffsetM));
 const currentGrip=getGripPosition(robot,config);
 const currentFlange=gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM)).positionM;
 const axis=sdk.positionM.map((x,i)=>(x-flange.positionM[i])/config.sdkToolOffsetM);
 const waypoint=(position,flangeM,gripM)=>({position:position.map(rounded),euler:[...sdk.eulerRad],flangeM:flangeM.map(rounded),gripM:gripM.map(rounded)});
 const contact=waypoint(sdk.positionM,flange.positionM,targetM);
 const preapproach=waypoint(sdk.positionM.map((x,i)=>x-axis[i]*config.preapproachM),flange.positionM.map((x,i)=>x-axis[i]*config.preapproachM),targetM.map((x,i)=>x-axis[i]*config.preapproachM));
 if(config.keepPreapproachSdkHeight===true){
  const dz=robot.flange_position_m[2]-preapproach.position[2];
  for(const point of [preapproach.position,preapproach.flangeM,preapproach.gripM])point[2]=rounded(point[2]+dz);
 }
 const lift=waypoint(sdk.positionM.map((x,i)=>x+(i===2?config.liftM:0)),flange.positionM.map((x,i)=>x+(i===2?config.liftM:0)),targetM.map((x,i)=>x+(i===2?config.liftM:0)));
 for(const point of [currentGrip,currentFlange,robot.flange_position_m,targetM,...[contact,preapproach,lift].flatMap(w=>[w.position,w.flangeM,w.gripM])])if(!inside(point,config))fail('workspace_limit');
 return {targetM,widthM,frameId:observation.frameId??observation.frame_id,contact,preapproach,lift,
  paths:{preapproach:segments(robot.flange_position_m,preapproach,config),approach:segments(preapproach.position,contact,config),lift:segments(contact.position,lift,config)}};
}
module.exports={buildGraspGeometry,getGripPosition,validateConfig,validateJoints,vector};
