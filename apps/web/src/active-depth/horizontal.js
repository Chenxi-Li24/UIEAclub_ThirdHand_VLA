'use strict';
const {ActiveDepthCoordinator,DEFAULT_LIMITS}=require('./coordinator');
const {streamPixelToRay,rayToStreamPixel}=require('./fisheye');
const {assertHorizontal,assertMotionStart,getGripPosition,validateJoints,vector}=require('../grasp/geometry');
const {gripTargetToFlangePose,flangeToGripPose}=require('../../../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');
const CENTER=[315.5,234],STEP_M=.005,MAX_TRAVEL_M=.04,MAX_YAW_RAD=10*Math.PI/180;
const distance=(a,b)=>Math.hypot(...a.map((x,i)=>x-b[i]));
const translation=x=>[[1,0,0,x],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
const angle=x=>Math.atan2(Math.sin(x),Math.cos(x));
function rotation([r,p,y]){
 const cr=Math.cos(r),sr=Math.sin(r),cp=Math.cos(p),sp=Math.sin(p),cy=Math.cos(y),sy=Math.sin(y);
 return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],[sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]];
}
const rotate=(m,v)=>m.map(row=>row.reduce((s,x,i)=>s+x*v[i],0));
const unrotate=(m,v)=>m[0].map((_,i)=>m.reduce((s,row,j)=>s+row[i]*v[j],0));
const angular=(a,b)=>Math.acos(Math.max(-1,Math.min(1,a.reduce((s,x,i)=>s+x*b[i],0))));
function sdkPose(grip,config){
 const flange=gripTargetToFlangePose(grip,config.T_flange_grasp_tcp||translation(config.gripOffsetM));
 const pose=flangeToGripPose(flange,translation(config.sdkToolOffsetM));
 return {position:pose.positionM,euler:pose.eulerRad};
}
function cameraPose(robot,mount,config){
 const flange=gripTargetToFlangePose({positionM:robot.flange_position_m,eulerRad:robot.flange_euler_rad},translation(config.sdkToolOffsetM));
 const pose=flangeToGripPose(flange,mount.matrix_4x4);
 return {position:pose.positionM,rotation:rotation(pose.eulerRad)};
}
function planHorizontalDepthStep({robot,startRobot,targetPixel,depthValid=false,mount,config}={}){
 try{
  assertMotionStart(robot,config);const heading=assertHorizontal(robot,config),startHeading=assertHorizontal(startRobot,config);
  if(!heading||!startHeading)return {ok:false,reason:'horizontal_configuration_required'};
  const ray=streamPixelToRay(targetPixel),desired=streamPixelToRay(CENTER);
  if(!ray.ok||!desired.ok)return {ok:false,reason:'invalid_target_pixel'};
  const current=cameraPose(robot,mount,config),start=cameraPose(startRobot,mount,config);
  const grip=getGripPosition(robot,config),bearingBase=rotate(current.rotation,ray.ray);
  const initialAngularErrorRad=angular(ray.ray,desired.ray);
  const candidate=(positionM,yaw,adjustment)=>{
   if(Math.abs(angle(yaw-startHeading[2]))>MAX_YAW_RAD+1e-9)return null;
   const targetSdkPose=sdkPose({positionM,eulerRad:[0,0,yaw]},config);
   const proposedRobot={...robot,flange_position_m:targetSdkPose.position,flange_euler_rad:targetSdkPose.euler};
   try{assertMotionStart(proposedRobot,config);assertHorizontal(proposedRobot,config);}catch{return null;}
   const proposed=cameraPose(proposedRobot,mount,config),cameraShiftM=distance(current.position,proposed.position);
   const cameraCumulativeM=distance(start.position,proposed.position);
   if(cameraShiftM>.01+1e-9||cameraCumulativeM>MAX_TRAVEL_M+1e-9)return null;
   const predictedRay=unrotate(proposed.rotation,bearingBase);
   return {ok:true,tier:'horizontal',adjustment,targetSdkPose,
    startSdkPose:{position:[...robot.flange_position_m],euler:[...robot.flange_euler_rad]},
    predictedPixel:adjustment==='yaw'?rayToStreamPixel(predictedRay).pixel:null,
    angularErrorRad:angular(predictedRay,desired.ray),initialAngularErrorRad,cameraShiftM,cameraCumulativeM};
  };
  if(distance(targetPixel,CENTER)>20){
   let best=null;
   for(const delta of [1,-1,.5,-.5].map(d=>d*Math.PI/180)){
    const p=candidate(grip,heading[2]+delta,'yaw');
    if(p&&p.angularErrorRad<initialAngularErrorRad-.00001&&(!best||p.angularErrorRad<best.angularErrorRad))best=p;
   }
   if(best)return best;
   // Sideways/up-down optical correction uses only a bearing, not an assumed
   // depth. Every result is checked again against the next measured RGB-D frame.
   const diff=ray.ray.map((x,i)=>x-desired.ray[i]);
   const along=diff.reduce((s,x,i)=>s+x*desired.ray[i],0);
   const side=diff.map((x,i)=>x-along*desired.ray[i]),norm=Math.hypot(...side);
   if(norm<1e-8)return {ok:false,reason:'horizontal_alignment_unreachable'};
   const shift=rotate(current.rotation,side.map(x=>STEP_M*x/norm));
   return candidate(grip.map((x,i)=>x+shift[i]),heading[2],'translate')||{ok:false,reason:'camera_limit'};
  }
  if(depthValid)return {ok:false,reason:'waiting_depth_frames'};
  // A centered bottle may be inside the 150 mm usable-depth edge. Back away,
  // never advance toward a target whose distance has not been measured.
  const back=rotate(current.rotation,[0,0,-STEP_M]);
  return candidate(grip.map((x,i)=>x+back[i]),heading[2],'backoff')||{ok:false,reason:'camera_limit'};
 }catch(e){return {ok:false,reason:e.code||e.message||'invalid_model_input'};}
}
class HorizontalDepthCoordinator extends ActiveDepthCoordinator{
 constructor({robotClient,visionClient,mount,getConfig,pollIntervalMs=100}){
  let self;
  super({visionClient,mount,pollIntervalMs,getRobotState:()=>robotClient.state(),
   planStep:options=>self._plan(options),limits:DEFAULT_LIMITS,
   executionClient:{execute:p=>self._execute(p),stop:()=>robotClient.stop(),close(){}}});
  self=this;Object.assign(this,{robotClient,getConfig});
 }
 async start(id){
  if(this.status().active||this.status().phase==='uncertain')throw Object.assign(Error('active_depth_active'),{code:'active_depth_active'});
  await this.robotClient.ready();
  if(this.status().active)throw Object.assign(Error('active_depth_active'),{code:'active_depth_active'});
  this.sessionConfig=structuredClone(this.getConfig());
  assertHorizontal(this.robotClient.state({idle:true}),this.sessionConfig);
  return super.start(id);
 }
 validateObservation(observation){
  const ts=Number(observation.observedAtMs??observation.ts),p=observation.frame_projection,c=this.sessionConfig;
  if(!Number.isFinite(ts)||this.now()-ts>c.visionMaxAgeMs||ts-this.now()>500)return 'vision_stale';
  if(ts<(this.session?.minimumCaptureMs??-Infinity))return 'vision_pre_motion';
  const barrier=this.session?.minimumRobotMonotonicNs;
  if(barrier!==undefined&&(!Number.isSafeInteger(p?.frame_monotonic_ns)||p.frame_monotonic_ns<barrier
   ||!Number.isSafeInteger(p?.robot_observed_monotonic_ns)||p.robot_observed_monotonic_ns<barrier))return 'vision_pre_motion';
  if(p?.status!=='ready')return 'vision_projection_unavailable';
  if(p.robot_frame_policy_id!==c.framePolicyId||p.calibration_id!==c.calibrationId)return 'frame_binding_mismatch';
  return null;
 }
 _terminal(phase,reason){
  const status=super._terminal(phase,reason);
  return phase==='uncertain'?this._publish({active:true,interlocked:true}):status;
 }
 async stop(sessionId){
  if(this.status().phase==='uncertain'&&this.session?.sessionId===sessionId){
   try{const result=await this.robotClient.stop();if(result.status!=='interrupted')throw Error('stop_unconfirmed');
    return this._publish({phase:'stopped',active:false,interlocked:false,reason:'operator_stop'});
   }catch{return this.status();}
  }
  return super.stop(sessionId);
 }
 async close(){
  if(this.status().phase==='uncertain'&&this.status().active)await this.stop(this.status().sessionId);
  if(this.status().phase==='uncertain'&&this.status().active)throw Object.assign(Error('stop_unconfirmed'),{code:'stop_unconfirmed'});
  await super.close();
 }
 async _plan(options){
  const config=this.sessionConfig,plan=planHorizontalDepthStep({...options,mount:this.mount,config});
  if(!plan.ok)return plan;
  const from=plan.startSdkPose,to=plan.targetSdkPose;
  const n=Math.max(1,Math.ceil(distance(from.position,to.position)/.005),Math.ceil(Math.abs(angle(to.euler[2]-from.euler[2]))/(.25*Math.PI/180)));
  let previous=options.robot.joints_deg;
  for(let i=1;i<=n;i++){
   if(this.session.stopRequested||this.session.terminal)return {ok:false,reason:'operator_stop'};
   const pose={position:from.position.map((x,j)=>x+(to.position[j]-x)*i/n),euler:from.euler.map((x,j)=>x+angle(to.euler[j]-x)*i/n)};
   const ik=await this.robotClient.preview(pose);
   if(!validateJoints(ik.joints_deg,config.jointLimits)||ik.joints_deg.some((x,j)=>Math.abs(x-previous[j])>(config.maxIkStepDeg||5)))return {ok:false,reason:'ik_discontinuity'};
   previous=ik.joints_deg;
  }
  return {...plan,targetJointsDeg:previous,jointDeltasDeg:previous.map((x,j)=>x-options.robot.joints_deg[j])};
 }
 async _execute(primitive){
  const p=primitive.parameters,robot=this.robotClient.state({idle:true}),failed=code=>({status:'failed',code,primitiveId:primitive.primitiveId});
  if(p.tier!=='horizontal'||!vector(p.targetSdkPose?.position)||!vector(p.targetSdkPose?.euler))return failed('alignment_invalid');
  if(distance(robot.flange_position_m,p.startSdkPose.position)>.001||robot.joints_deg.some((x,j)=>Math.abs(x-p.startJointsDeg[j])>.3))return failed('alignment_start_changed');
  assertHorizontal(robot,this.sessionConfig);
  const started=Date.now();
  try{
   const result=await this.robotClient.command({cmd:'move_l',position:p.targetSdkPose.position,euler:p.targetSdkPose.euler,request_id:primitive.primitiveId},this.sessionConfig.commandTimeoutMs||15000);
   const after=this.robotClient.state({idle:true});assertHorizontal(after,this.sessionConfig);
   const reached=result.reached===true&&distance(after.flange_position_m,p.targetSdkPose.position)<=.015;
   return {status:reached?'completed':'failed',code:reached?'target_reached':'alignment_not_reached',primitiveId:primitive.primitiveId,
    completedAfterMs:this.now(),...(Number.isSafeInteger(after.producer_monotonic_ns)?{completedRobotMonotonicNs:after.producer_monotonic_ns}:{})};
  }catch(error){
   try{
    const stopped=this.robotClient.lastStopAt>=started&&this.robotClient.lastStopPromise
     ?await this.robotClient.lastStopPromise:await this.robotClient.stop();
    if(stopped.status!=='interrupted')throw Error('stop_unconfirmed');
    return failed(error.code||error.message||'alignment_failed');
   }catch{return {status:'uncertain',code:'stop_unconfirmed',primitiveId:primitive.primitiveId};}
  }
 }
}
module.exports={planHorizontalDepthStep,HorizontalDepthCoordinator};
