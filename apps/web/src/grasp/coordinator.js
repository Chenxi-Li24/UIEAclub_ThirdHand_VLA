'use strict';
const {EventEmitter}=require('node:events');
const {randomUUID}=require('node:crypto');
const {buildGraspGeometry,validateConfig,validateJoints,vector,getGripPosition}=require('./geometry');
const delay=ms=>new Promise(r=>setTimeout(r,ms));
function fault(code){const e=new Error(code);e.code=code;return e;}
const distance=(a,b)=>Math.hypot(...a.map((x,i)=>x-b[i]));
class GraspCoordinator extends EventEmitter{
 constructor({config,robotClient,visionClient,depthCoordinator,now=Date.now,sleep=delay,audit=()=>{}}){
  super();validateConfig(config);Object.assign(this,{config,robotClient,visionClient,depthCoordinator,now,sleep,audit});
  this.requests=new Map();this.session=null;this.current={type:'grasp.status',phase:'idle',active:false,sessionId:null,gripOffsetM:config.gripOffsetM,legacyGraspEnabled:false};
 }
 status(){return JSON.parse(JSON.stringify(this.current));}
 _record(type,data){const event={ts:this.now(),sessionId:this.session?.id,type,...data};this.audit(event);this.emit('trace',event);}
 _publish(changes){this.current={...this.current,...changes};this._record('status',{status:this.current});this.emit('status',this.status());}
 _alive(s){if(this.session!==s||s.canceled||s.terminal)throw fault('operator_stop');if(this.now()-s.startedAt>240000)throw fault('workflow_timeout');}
 async start(stableId,requestId){
  if(!Number.isSafeInteger(stableId)||stableId<1||stableId>5||typeof requestId!=='string'||!/^[\w:-]{1,120}$/.test(requestId))throw fault('request_invalid');
  const existing=this.requests.get(requestId);if(existing){if(existing.stableId!==stableId)throw fault('request_id_conflict');return existing.result||this.status();}
  if(this.current.active)throw fault('grasp_active');
  if(this.requests.size>=100)throw fault('request_history_full');
  const s={id:randomUUID(),requestId,stableId,startedAt:this.now(),inFlight:false,canceled:false,terminal:false,motionUncertain:false,holding:false};
  this.session=s;this.requests.set(requestId,s);this.robotClient.ownerTag='web-grasp:'+s.id;
  this._publish({phase:'depth_acquiring',active:true,sessionId:s.id,requestId,stableId,reason:null,holding:false,completedSegments:0,depthValidFrames:0,result:null});
  this._run(s).catch(async e=>{
   if(s.terminal)return;
   let phase='failed';
   if(s.motionUncertain&&!(this.robotClient.lastStopAt>=s.startedAt)){
    try{await this.robotClient.stop();}catch{phase='uncertain';}
   }
   this._terminal(s,phase,e.code||e.message||'grasp_failed');
  });return this.status();
 }
 _terminal(s,phase,reason,result=null){
  if(s.terminal)return;s.terminal=true;
  this._publish({phase,active:false,reason,holding:s.holding,result});s.result=this.status();this.robotClient.ownerTag=null;
 }
 async _depth(s){
  let count=0,lastFrame=-1,aligned=false;const until=this.now()+95000;
  while(this.now()<until){
   this._alive(s);const {observation}=await this.visionClient.snapshot(s.stableId);
   this._alive(s);const id=Number(observation.frameId??observation.frame_id);
   const ts=Number(observation.observedAtMs??observation.ts);
   if(!Number.isSafeInteger(id)||!Number.isFinite(ts)||this.now()-ts>this.config.visionMaxAgeMs)throw fault('vision_stale');
   const target=(observation.targets||[]).find(t=>Number(t.stable_id??t.stableId)===s.stableId);
   if(Number(observation.selectedStableId??observation.selected_stable_id)!==s.stableId||!target||target.track_state!=='confirmed')throw fault('target_lost');
   if(id<=lastFrame){await this.sleep(100);continue;}lastFrame=id;
   if(target.depth_valid===true&&vector(target.camera_xyz_m)&&observation.frame_projection?.status==='ready'){
    count++;this._publish({depthValidFrames:count});
    if(count>=3)return observation;
   }else{
    count=0;
    if(aligned)throw fault('depth_invalid');aligned=true;
    await this.depthCoordinator.start(s.stableId);
    while(this.depthCoordinator.status().active){this._alive(s);this._publish({depth:this.depthCoordinator.status()});await this.sleep(100);}
    if(this.depthCoordinator.status().phase!=='depth_acquired')throw fault(this.depthCoordinator.status().reason||'depth_acquisition_failed');
   }
   await this.sleep(100);
  }throw fault('depth_timeout');
 }
 _geometry(observation,s){return buildGraspGeometry({observation,stableId:s.stableId,robot:this.robotClient.state({idle:true}),config:this.config,now:this.now()});}
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
  catch(e){if(['move_l','servo'].includes(command.cmd)&&['feedback_stale','feedback_invalid','web_disconnected','web_transport_error','command_timeout','web_send_failed'].includes(e.code))s.motionUncertain=true;throw e;}
  finally{s.inFlight=false;}
 }
 _path(from,to){const n=Math.max(1,Math.ceil(distance(from,to.position)/this.config.segmentM));if(n>200)throw fault('path_too_long');
  return Array.from({length:n},(_,i)=>({position:from.map((x,j)=>Number((x+(to.position[j]-x)*(i+1)/n).toFixed(12))),euler:[...to.euler]}));}
 async _move(path,phase,s){
  this._publish({phase});
  for(const pose of path){
   this._alive(s);const before=this.robotClient.state({idle:true});
   if(distance(before.flange_position_m,pose.position)>this.config.segmentM+this.config.positionToleranceM)throw fault('segment_start_changed');
   const ik=await this.robotClient.preview(pose);this._alive(s);
   if(!validateJoints(ik.joints_deg,this.config.jointLimits)||ik.joints_deg.some((x,i)=>Math.abs(x-before.joints_deg[i])>this.config.maxIkStepDeg))throw fault('ik_discontinuity');
   const started=this.now();await this._command({cmd:'move_l',position:pose.position,euler:pose.euler,
    position_tolerance_m:this.config.positionToleranceM,orientation_tolerance_rad:this.config.orientationToleranceRad},s);
   const after=await this._stable(s);
   if(distance(after.flange_position_m,pose.position)>this.config.positionToleranceM||after.flange_euler_rad.some((x,i)=>Math.abs(Math.atan2(Math.sin(x-pose.euler[i]),Math.cos(x-pose.euler[i])))>this.config.orientationToleranceRad))throw fault('pose_not_reached');
   this._record('actual_pose',{state:after});this._publish({completedSegments:this.current.completedSegments+1});
   await this.sleep(Math.max(0,this.config.stepIntervalMs-(this.now()-started)));
  }
 }
 async _run(s){
  await this.robotClient.ready();this._alive(s);
  const observation=await this._depth(s);this._publish({phase:'planning'});
  let g=this._geometry(observation,s);this._publish({targetM:g.targetM,widthM:g.widthM,phase:'path_checking'});
  await this._check([...g.paths.preapproach,...g.paths.approach,...g.paths.lift],s);
  this._publish({phase:'opening'});await this._command({cmd:'gripper',position:1},s);
  if((await this._stable(s)).gripper_width_m<0.074)throw fault('gripper_not_open');
  await this._move(g.paths.preapproach,'preapproach',s);this._publish({phase:'target_refresh',depthValidFrames:0});
  const refreshed=await this._depth(s),updated=this._geometry(refreshed,s);
  if(distance(updated.targetM,g.targetM)>0.04)throw fault('target_moved');g=updated;
  const approach=this._path(this.robotClient.state({idle:true}).flange_position_m,g.contact);
  if(distance(this.robotClient.state().flange_position_m,g.contact.position)>0.14)throw fault('approach_distance_changed');
  await this._check([...approach,...g.paths.lift],s);await this._move(approach,'approach',s);
  this._publish({phase:'closing'});await this._command({cmd:'gripper',position:0},s);
  const contact=await this._stable(s);
  if(contact.gripper_width_m<this.config.contactMinM||contact.gripper_width_m>this.config.contactMaxM||contact.gripper_width_m>g.widthM+0.025)throw fault('contact_not_observed');
  s.holding=true;this._publish({holding:true});await this._move(this._path(contact.flange_position_m,g.lift),'lifting',s);
  const final=this.robotClient.state({idle:true});
  if(final.gripper_width_m<this.config.contactMinM||final.gripper_width_m>this.config.contactMaxM){s.holding=false;throw fault('contact_lost');}
  this._terminal(s,'complete',null,{pipelineComplete:true,physicalGraspVerified:false,targetM:g.targetM,actualSdkM:final.flange_position_m,
   actualGripM:getGripPosition(final,this.config),gripperWidthM:final.gripper_width_m,liftM:this.config.liftM});
 }
 async stop(sessionId){
  const s=this.session;if(!s||s.id!==sessionId||s.terminal)return this.status();s.canceled=true;
  if(this.depthCoordinator.status().active){await this.depthCoordinator.stop(this.depthCoordinator.status().sessionId);}
  let phase='stopped';if(s.inFlight||this.robotClient.last?.moving){try{await this.robotClient.stop();}catch{phase='uncertain';}}
  this._terminal(s,phase,'operator_stop');return this.status();
 }
 async close(){if(this.current.active)await this.stop(this.current.sessionId);await this.depthCoordinator.close();this.robotClient.close();}
}
module.exports={GraspCoordinator};
