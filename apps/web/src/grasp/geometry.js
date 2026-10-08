'use strict';
const {validateRigidTransform,gripTargetToFlangePose,flangeToGripPose}=require('../../../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');
const vector=(v,n=3)=>Array.isArray(v)&&v.length===n&&Array.from(v).every(Number.isFinite);
const rounded=x=>Number(x.toFixed(12));
function fail(code){const e=new Error(code);e.code=code;throw e;}
function translation(x){return [[1,0,0,x],[0,1,0,0],[0,0,1,0],[0,0,0,1]];}
function validateJoints(q,limits){return vector(q,6)&&Array.isArray(limits)&&limits.length===6&&q.every((x,i)=>vector(limits[i],2)&&x>=limits[i][0]&&x<=limits[i][1]);}
function validateConfig(c){
 if(c?.orientationMode!==undefined&&!['preserve','horizontal'].includes(c.orientationMode))fail('grasp_config_invalid');
 if(c?.executionMode!==undefined&&!['segmented','phase_linear'].includes(c.executionMode))fail('grasp_config_invalid');
 if(c?.horizontalToleranceRad!==undefined&&(!Number.isFinite(c.horizontalToleranceRad)||c.horizontalToleranceRad<=0||c.horizontalToleranceRad>.1))fail('grasp_config_invalid');
 if(c?.horizontalYawRad!==undefined&&!Number.isFinite(c.horizontalYawRad))fail('grasp_config_invalid');
 if(c?.depthTimeoutMs!==undefined&&(!Number.isFinite(c.depthTimeoutMs)||c.depthTimeoutMs<1000||c.depthTimeoutMs>95000))fail('grasp_config_invalid');
 for(const k of ['gripOffsetM','sdkToolOffsetM','preapproachM','liftM','segmentM','visionMaxAgeMs'])if(!Number.isFinite(c?.[k])||c[k]<=0)fail('grasp_config_invalid');
 if(c.segmentM>0.005||c.gripOffsetM>0.3||c.sdkToolOffsetM>0.3||c.preapproachM>0.2||c.liftM>0.1)fail('grasp_config_invalid');
 if(c.maxApproachM!==undefined&&(!Number.isFinite(c.maxApproachM)||c.maxApproachM<c.preapproachM||c.maxApproachM>0.25))fail('grasp_config_invalid');
 if(c.forwardBackoffM!==undefined&&(!Number.isFinite(c.forwardBackoffM)||c.forwardBackoffM<0||c.forwardBackoffM>0.1))fail('grasp_config_invalid');
 for(const k of ['framePolicyId','calibrationId'])if(!/^sha256:[a-f0-9]{64}$/.test(c[k]))fail('grasp_config_invalid');
 for(const k of ['x','y','z'])if(!vector(c.workspace?.[k],2)||c.workspace[k][0]>=c.workspace[k][1])fail('grasp_config_invalid');
 if(!Array.isArray(c.jointLimits)||c.jointLimits.length!==6||c.jointLimits.some(x=>!vector(x,2)||x[0]>=x[1]))fail('grasp_config_invalid');
 if(c.legacyGraspEnabled===true)fail('legacy_grasp_must_stay_disabled');return c;
}
function gripTransform(config){return validateRigidTransform(config.T_flange_grasp_tcp||translation(config.gripOffsetM));}
function currentGripPose(robot,config){
 const flange=gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM));
 return flangeToGripPose(flange,gripTransform(config));
}
function assertHorizontal(robot,config){
 if(config.orientationMode!=='horizontal')return;
 const euler=currentGripPose(robot,config).eulerRad,tolerance=config.horizontalToleranceRad??.05;
 if(!Number.isFinite(tolerance)||tolerance<=0||tolerance>.1)fail('grasp_config_invalid');
 if(euler.slice(0,2).some(angle=>Math.abs(Math.atan2(Math.sin(angle),Math.cos(angle)))>tolerance))fail('tool_not_horizontal');
 return [0,0,euler[2]];
}
function inside(p,c){return vector(p)&&['x','y','z'].every((axis,i)=>p[i]>=c.workspace[axis][0]&&p[i]<=c.workspace[axis][1]);}
function getGripPosition(robot,config){
 if(!vector(robot?.flange_position_m)||!vector(robot?.flange_euler_rad))fail('robot_pose_invalid');
 return currentGripPose(robot,config).positionM.map(rounded);
}
function assertMotionStart(robot,config){
 if(!validateJoints(robot.joints_deg,config.jointLimits))fail('robot_pose_invalid');
 const grip=getGripPosition(robot,config);
 const flange=gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM)).positionM;
 for(const point of [grip,flange,robot.flange_position_m])if(!inside(point,config))fail('workspace_limit');
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
 const width=observation.pose?.width_m;
 const widthM=Number.isFinite(width)&&width>=0.008&&width<=0.072?width:null;
 assertHorizontal(robot,config);
 const currentEuler=currentGripPose(robot,config).eulerRad;
 const desired={positionM:targetM,eulerRad:config.orientationMode==='horizontal'?[0,0,config.horizontalYawRad??currentEuler[2]]:currentEuler};
 const flange=gripTargetToFlangePose(desired,gripTransform(config));
 const sdk=flangeToGripPose(flange,translation(config.sdkToolOffsetM));
 const currentGrip=getGripPosition(robot,config);
 const currentFlange=gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM)).positionM;
 const axis=sdk.positionM.map((x,i)=>(x-flange.positionM[i])/config.sdkToolOffsetM);
 const waypoint=(position,flangeM,gripM)=>({position:position.map(rounded),euler:[...sdk.eulerRad],flangeM:flangeM.map(rounded),gripM:gripM.map(rounded)});
 // Keep the already-verified visibility checkpoint; shortening contact travel must not move it closer to the base.
 const preapproach=waypoint(sdk.positionM.map((x,i)=>x-axis[i]*config.preapproachM),flange.positionM.map((x,i)=>x-axis[i]*config.preapproachM),targetM.map((x,i)=>x-axis[i]*config.preapproachM));
 const backoff=config.forwardBackoffM??0,horizontal=Math.hypot(axis[0],axis[1]);
 if(backoff>0&&horizontal<0.2)fail('forward_axis_invalid');
 // Operator-observed forward overshoot is a horizontal motion correction, not a new TCP or hand-eye calibration.
 const correction=backoff>0?[axis[0]*backoff/horizontal,axis[1]*backoff/horizontal,0]:[0,0,0];
 const gripM=targetM.map((x,i)=>x-correction[i]);
 flange.positionM=flange.positionM.map((x,i)=>x-correction[i]);sdk.positionM=sdk.positionM.map((x,i)=>x-correction[i]);
 const contact=waypoint(sdk.positionM,flange.positionM,gripM);
 if(config.keepPreapproachSdkHeight===true){
  const dz=robot.flange_position_m[2]-preapproach.position[2];
  for(const point of [preapproach.position,preapproach.flangeM,preapproach.gripM])point[2]=rounded(point[2]+dz);
 }
 const lift=waypoint(sdk.positionM.map((x,i)=>x+(i===2?config.liftM:0)),flange.positionM.map((x,i)=>x+(i===2?config.liftM:0)),gripM.map((x,i)=>x+(i===2?config.liftM:0)));
 for(const point of [currentGrip,currentFlange,robot.flange_position_m,targetM,...[contact,preapproach,lift].flatMap(w=>[w.position,w.flangeM,w.gripM])])if(!inside(point,config))fail('workspace_limit');
 return {targetM,widthM,forwardBackoffM:backoff,frameId:observation.frameId??observation.frame_id,contact,preapproach,lift,
  paths:{preapproach:segments(robot.flange_position_m,preapproach,config),approach:segments(preapproach.position,contact,config),lift:segments(contact.position,lift,config)}};
}
module.exports={buildGraspGeometry,getGripPosition,validateConfig,validateJoints,vector,assertHorizontal,assertMotionStart};
