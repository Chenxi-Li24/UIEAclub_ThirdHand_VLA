'use strict';
const {EventEmitter}=require('node:events');
const {randomUUID}=require('node:crypto');
const {buildGraspGeometry,validateConfig,validateJoints,vector,getGripPosition,assertHorizontal,assertMotionStart}=require('./geometry');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function fault(code){const e=new Error(code);e.code=code;return e;}
const distance=(a,b)=>Math.hypot(...a.map((x,i)=>x-b[i]));
class GraspCoordinator extends EventEmitter{
 constructor({config,robotClient,visionClient,depthCoordinator,resolveTcp=()=>null,now=Date.now,sleep=delay,audit=()=>{}}){
  super();validateConfig(config);Object.assign(this,{config,robotClient,visionClient,depthCoordinator,resolveTcp,now,sleep,audit});
  this.requests=new Map();this.session=null;this.current={type:'grasp.status',phase:'idle',active:false,sessionId:null,gripOffsetM:config.gripOffsetM,legacyGraspEnabled:false};
 }
 status(){return JSON.parse(JSON.stringify(this.current));}
 motionConfiguration(){return {orientationMode:this.config.orientationMode||'preserve',executionMode:this.config.executionMode||'segmented',
  sampleM:this.config.segmentM,requestedSpeedScale:this.config.requestedSpeedScale??null};}
 tcpConfiguration(){
  if(this.current.active&&this.current.tcp)return structuredClone(this.current.tcp);
  const measured=this.resolveTcp();
  return measured?{...structuredClone(measured),forwardBackoffM:this.config.calibratedForwardBackoffM??0}
   :{source:'approximate',id:null,T_flange_grasp_tcp:[[1,0,0,this.config.gripOffsetM],[0,1,0,0],[0,0,1,0],[0,0,0,1]],forwardBackoffM:this.config.forwardBackoffM??0};
 }
 _record(type,data){const event={ts:this.now(),sessionId:this.session?.id,type,...data};this.audit(event);this.emit('trace',event);}
 _publish(changes){this.current={...this.current,...changes};this._record('status',{status:this.current});this.emit('status',this.status());}
 _alive(s){if(this.session!==s||s.canceled||s.terminal)throw fault('operator_stop');if(this.now()-s.startedAt>240000)throw fault('workflow_timeout');}
 async start(stableId,requestId){
  if(!Number.isSafeInteger(stableId)||stableId<1||stableId>5||typeof requestId!=='string'||!/^[\w:-]{1,120}$/.test(requestId))throw fault('request_invalid');
  const existing=this.requests.get(requestId);if(existing){if(existing.stableId!==stableId)throw fault('request_id_conflict');return existing.result||this.status();}
  if(this.current.active)throw fault('grasp_active');
  if(this.requests.size>=100)throw fault('request_history_full');
  const tcp=this.tcpConfiguration();
  const sessionConfig=structuredClone({...this.config,T_flange_grasp_tcp:tcp.T_flange_grasp_tcp,forwardBackoffM:tcp.forwardBackoffM});
  validateConfig(sessionConfig);
  const s={id:randomUUID(),requestId,stableId,startedAt:this.now(),inFlight:false,canceled:false,terminal:false,motionUncertain:false,holding:false};
  s.config=sessionConfig;
  this.session=s;this.requests.set(requestId,s);this.robotClient.ownerTag='web-grasp:'+s.id;
  this._publish({phase:'depth_acquiring',active:true,sessionId:s.id,requestId,stableId,reason:null,holding:false,tcp,
   targetM:null,widthM:null,plan:null,progress:null,depth:null,completedSegments:0,depthValidFrames:0,result:null});
  this._run(s).catch(async e=>{
   // Cancellation owns its finalizer; a command rejected by stop() must not
   // release the arm before that same stop is confirmed.
   if(s.terminal||s.canceled)return;
   let phase='failed';
   if(s.motionUncertain){
    try{if(this.robotClient.lastStopAt>=s.startedAt&&this.robotClient.lastStopPromise)await this.robotClient.lastStopPromise;else await this.robotClient.stop();}catch{phase='uncertain';}
   }
   if(!s.canceled)this._terminal(s,phase,e.code||e.message||'grasp_failed');
  });return this.status();
 }
 _terminal(s,phase,reason,result=null){
  if(s.terminal)return;s.terminal=true;
  this._publish({phase,active:phase==='uncertain',interlocked:phase==='uncertain',reason,holding:s.holding,result});s.result=this.status();if(phase!=='uncertain')this.robotClient.ownerTag=null;
 }
 async _snapshot(s){
  for(let i=0;i<20;i++){
   this._alive(s);
   try{return await this.visionClient.snapshot(s.stableId);}
   catch(e){
    if(!['vision_evidence_mismatch','vision_projection_mismatch'].includes(e.code))throw e;
    this._record('vision_wait',{attempt:i+1,reason:e.code});
    await this.sleep(100);
   }
  }throw fault('vision_evidence_timeout');
 }
 async _depth(s){
  let count=0,lastFrame=-1,aligned=false;const until=this.now()+(s.config.depthTimeoutMs??95000);
  while(this.now()<until){
   this._alive(s);const {observation}=await this._snapshot(s);
   this._alive(s);const id=Number(observation.frameId??observation.frame_id);
   const ts=Number(observation.observedAtMs??observation.ts);
   if(!Number.isSafeInteger(id)||!Number.isFinite(ts)||this.now()-ts>this.config.visionMaxAgeMs)throw fault('vision_stale');
   const target=(observation.targets||[]).find(t=>Number(t.stable_id??t.stableId)===s.stableId);
   if(Number(observation.selectedStableId??observation.selected_stable_id)!==s.stableId||!target||target.track_state!=='confirmed')throw fault('target_lost');
   if(id<=lastFrame){await this.sleep(100);continue;}lastFrame=id;
   // An invalidated projection is not missing depth. Wait for synchronized
   // stationary evidence rather than starting an unnecessary robot correction.
   if(observation.frame_projection?.status!=='ready'){
    count=0;this._publish({depthValidFrames:0});await this.sleep(100);continue;
   }
   if(target.depth_valid===true&&vector(target.camera_xyz_m)){
    count++;this._publish({depthValidFrames:count});
    if(count>=3)return observation;
   }else{
    count=0;
    if(aligned){this._publish({depthValidFrames:0});await this.sleep(100);continue;}aligned=true;
    await this.depthCoordinator.start(s.stableId);
    while(this.depthCoordinator.status().active&&this.depthCoordinator.status().phase!=='uncertain'){this._alive(s);this._publish({depth:this.depthCoordinator.status()});await this.sleep(100);}
    const depth=this.depthCoordinator.status();
    this._publish({depth});
    if(depth.phase==='uncertain')s.motionUncertain=true;
    if(depth.phase!=='depth_acquired')throw fault(depth.reason||'depth_acquisition_failed');
   }
   await this.sleep(100);
  }throw fault('depth_timeout');
 }
 _geometry(observation,s){return buildGraspGeometry({observation,stableId:s.stableId,robot:this.robotClient.state({idle:true}),config:s.config,now:this.now()});}
 async _check(paths,s){
  let before=this.robotClient.state({idle:true}).joints_deg;
  for(const pose of paths){
   this._alive(s);const ik=await this.robotClient.preview(pose);this._alive(s);
   if(!validateJoints(ik.joints_deg,this.config.jointLimits))throw fault('ik_invalid');
   if(ik.joints_deg.some((x,i)=>Math.abs(x-before[i])>this.config.maxIkStepDeg))throw fault('ik_discontinuity');
   this._record('path_sample',{pose,jointsDeg:ik.joints_deg});before=ik.joints_deg;
  }
 }
 async _stable(s){
  let previous=null,stable=0,lastSequence=-1;
  for(let i=0;i<40;i++){
   this._alive(s);const state=this.robotClient.state();
   if(state.moving===true||state.stateName!=='IDLE'){stable=0;await this.sleep(100);continue;}
   if(state.state_sequence>lastSequence){
    stable=previous&&state.joints_deg.every((x,j)=>Math.abs(x-previous.joints_deg[j])<0.3)&&Math.abs(state.gripper_width_m-previous.gripper_width_m)<0.001?stable+1:1;
    lastSequence=state.state_sequence;previous=state;if(stable>=3)return state;
   }await this.sleep(100);
  }throw fault('robot_not_settled');
 }
 async _command(command,s){
  this._alive(s);s.inFlight=true;this._record('command',{command});
  try{const result=await this.robotClient.command(command,this.config.commandTimeoutMs);this._record('completion',{command:command.cmd,result});this._alive(s);return result;}
  catch(e){if(['move_l','servo'].includes(command.cmd)&&(e.motionUncertain||['feedback_stale','feedback_invalid','web_disconnected','web_transport_error','command_timeout','web_send_failed'].includes(e.code)))s.motionUncertain=true;throw e;}
  finally{s.inFlight=false;}
 }
 _path(from,to){const n=Math.max(1,Math.ceil(distance(from,to.position)/this.config.segmentM));if(n>200)throw fault('path_too_long');
  return Array.from({length:n},(_,i)=>({position:from.map((x,j)=>Number((x+(to.position[j]-x)*(i+1)/n).toFixed(12))),euler:[...to.euler]}));}
 async _move(path,phase,s){
  if(s.config.executionMode==='phase_linear')return this._moveLinear(path,phase,s);
  this._publish({phase,progress:{stage:phase,completed:0,total:path.length}});
  for(const pose of path){
   if(phase==='preapproach')await this._target(s);
   this._alive(s);const before=this.robotClient.state({idle:true});
   if(distance(before.flange_position_m,pose.position)>this.config.segmentM+this.config.positionToleranceM)throw fault('segment_start_changed');
   const ik=await this.robotClient.preview(pose);this._alive(s);
   if(!validateJoints(ik.joints_deg,this.config.jointLimits)||ik.joints_deg.some((x,i)=>Math.abs(x-before.joints_deg[i])>this.config.maxIkStepDeg))throw fault('ik_discontinuity');
   if(phase==='preapproach')await this._target(s);
   const started=this.now();await this._command({cmd:'move_l',position:pose.position,euler:pose.euler,
    position_tolerance_m:this.config.positionToleranceM,orientation_tolerance_rad:this.config.orientationToleranceRad},s);
   const after=await this._stable(s);
   if(distance(after.flange_position_m,pose.position)>this.config.positionToleranceM||after.flange_euler_rad.some((x,i)=>Math.abs(Math.atan2(Math.sin(x-pose.euler[i]),Math.cos(x-pose.euler[i])))>this.config.orientationToleranceRad))throw fault('pose_not_reached');
   this._record('actual_pose',{state:after});this._publish({completedSegments:this.current.completedSegments+1,
    progress:{stage:phase,completed:this.current.progress.completed+1,total:path.length}});
   await this.sleep(Math.max(0,this.config.stepIntervalMs-(this.now()-started)));
  }
 }
 async _moveLinear(path,phase,s){
  if(!path.length)throw fault('path_invalid');
  const before=this.robotClient.state({idle:true});assertHorizontal(before,s.config);assertMotionStart(before,s.config);
  if(distance(before.flange_position_m,path[0].position)>this.config.segmentM+this.config.positionToleranceM)throw fault('segment_start_changed');
  path=this._path(before.flange_position_m,path.at(-1));
  this._publish({phase,progress:{stage:phase,completed:0,total:1,checkedSamples:path.length}});
  if(phase==='preapproach')await this._target(s);
  // The 5mm path is still checked in full. It is sampling, not a queue of
  // independently stopping actuator commands. SDK move_l owns interpolation.
  await this._check(path,s);
  if(phase==='preapproach')await this._target(s);
  const start=this.robotClient.state({idle:true});assertHorizontal(start,s.config);assertMotionStart(start,s.config);
  if(distance(start.flange_position_m,before.flange_position_m)>.001||start.joints_deg.some((x,i)=>Math.abs(x-before.joints_deg[i])>.3))throw fault('segment_start_changed');
  const pose=path.at(-1);
  let finished=false;
  const command=this._command({cmd:'move_l',position:pose.position,euler:pose.euler,
   position_tolerance_m:this.config.positionToleranceM,orientation_tolerance_rad:this.config.orientationToleranceRad},s);
  const watch=async()=>{
   while(!finished){
    await this.sleep(100);if(finished)return;
    try{await this._target(s,true);}catch(error){if(finished)return;s.motionUncertain=true;throw error;}
   }
  };
  try{await (phase==='preapproach'?Promise.race([command,watch()]):command);}
  finally{finished=true;}
  const after=await this._stable(s);assertHorizontal(after,s.config);
  if(distance(after.flange_position_m,pose.position)>this.config.positionToleranceM||after.flange_euler_rad.some((x,i)=>Math.abs(Math.atan2(Math.sin(x-pose.euler[i]),Math.cos(x-pose.euler[i])))>this.config.orientationToleranceRad))throw fault('pose_not_reached');
  this._record('actual_pose',{state:after});this._publish({completedSegments:this.current.completedSegments+1,
   progress:{stage:phase,completed:1,total:1,checkedSamples:path.length}});
 }
 async _target(s,trackingOnly=false){
  this._alive(s);const {observation}=trackingOnly
   ?await this.visionClient.trackingSnapshot(s.stableId):await this._snapshot(s);this._alive(s);
  const ts=Number(observation.observedAtMs??observation.ts),target=(observation.targets||[]).find(t=>Number(t.stable_id??t.stableId)===s.stableId);
  if(!Number.isFinite(ts)||this.now()-ts>this.config.visionMaxAgeMs||ts-this.now()>500)throw fault('vision_stale');
  if(Number(observation.selectedStableId??observation.selected_stable_id)!==s.stableId||!target||target.track_state!=='confirmed')throw fault('target_lost');
 }
 async _run(s){
  await this.robotClient.ready();this._alive(s);
  const horizontal=assertHorizontal(this.robotClient.state({idle:true}),s.config);
  if(horizontal)s.config.horizontalYawRad=horizontal[2];
  const observation=await this._depth(s);
  if(horizontal)s.config.horizontalYawRad=assertHorizontal(this.robotClient.state({idle:true}),s.config)[2];
  this._publish({phase:'planning'});
  let g=this._geometry(observation,s);this._publishPlan(g);this._publish({phase:'path_checking'});
  await this._check([...g.paths.preapproach,...g.paths.approach,...g.paths.lift],s);
  await this._target(s);this._publish({phase:'opening'});await this._command({cmd:'gripper',position:1},s);
  if((await this._stable(s)).gripper_width_m<0.074)throw fault('gripper_not_open');
  await this._move(g.paths.preapproach,'preapproach',s);this._publish({phase:'target_refresh',depthValidFrames:0});
  const refreshed=await this._depth(s);
  if(horizontal)s.config.horizontalYawRad=assertHorizontal(this.robotClient.state({idle:true}),s.config)[2];
  const updated=this._geometry(refreshed,s);
  if(distance(updated.targetM,g.targetM)>0.04)throw fault('target_moved');g=updated;
  this._publishPlan(g);
  const approach=this._path(this.robotClient.state({idle:true}).flange_position_m,g.contact);
  if(distance(this.robotClient.state().flange_position_m,g.contact.position)>(this.config.maxApproachM??0.14))throw fault('approach_distance_changed');
  await this._check([...approach,...g.paths.lift],s);await this._move(approach,'approach',s);
  this._publish({phase:'closing'});await this._command({cmd:'gripper',position:0},s);
  const contact=await this._stable(s);
  if(contact.gripper_width_m<this.config.contactMinM||contact.gripper_width_m>this.config.contactMaxM)throw fault('contact_not_observed');
  s.holding=true;this._publish({holding:true});await this._move(this._path(contact.flange_position_m,g.lift),'lifting',s);
  const final=this.robotClient.state({idle:true});
  if(final.gripper_width_m<this.config.contactMinM||final.gripper_width_m>this.config.contactMaxM){s.holding=false;throw fault('contact_lost');}
  this._terminal(s,'complete',null,{pipelineComplete:true,physicalGraspVerified:false,targetM:g.targetM,actualSdkM:final.flange_position_m,
   actualGripM:getGripPosition(final,s.config),gripperWidthM:final.gripper_width_m,liftM:this.config.liftM,tcp:this.current.tcp});
 }
 _publishPlan(g){this._publish({targetM:g.targetM,widthM:g.widthM,frameId:g.frameId,
  plan:{preapproach:g.preapproach,contact:g.contact,lift:g.lift,
   segments:Object.fromEntries(Object.entries(g.paths).map(([key,value])=>[key,value.length]))}});}
 async stop(sessionId){
  const s=this.session;if(!s||s.id!==sessionId||(s.terminal&&this.current.phase!=='uncertain'))return this.status();
  if(s.stopPromise)return s.stopPromise;
  const retry=s.terminal;s.canceled=true;
  const motion=s.inFlight||s.motionUncertain||this.robotClient.last?.moving;
  this._publish({phase:'stopping',active:true,interlocked:true,reason:'operator_stop'});
  s.stopPromise=(async()=>{
   let phase='stopped',needsStop=motion||retry;
   try{
    const depth=this.depthCoordinator.status();
    if(depth.active){
     const outcome=await this.depthCoordinator.stop(depth.sessionId);
     if(outcome?.phase==='uncertain')needsStop=true;
    }else if(depth.phase==='uncertain')needsStop=true;
    if(needsStop){
     if(!retry&&this.robotClient.lastStopAt>=s.startedAt&&this.robotClient.lastStopPromise)await this.robotClient.lastStopPromise;
     else await this.robotClient.stop();
    }
   }catch{phase='uncertain';}
   // A confirmed retry can resolve a previously terminal uncertain session.
   if(retry)s.terminal=false;
   this._terminal(s,phase,'operator_stop');return this.status();
  })();
  try{return await s.stopPromise;}finally{s.stopPromise=null;}
 }
 async close(){if(this.current.active)await this.stop(this.current.sessionId);await this.depthCoordinator.close();this.robotClient.close();}
}
module.exports={GraspCoordinator};
