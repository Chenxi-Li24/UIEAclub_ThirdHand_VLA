'use strict';
const {EventEmitter}=require('node:events');
const {randomUUID}=require('node:crypto');
const WebSocket=require('ws');
const {validateJoints,vector}=require('./geometry');
const DEFAULT_LIMITS=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];
const ALLOWED=new Set(['servo','move_l','preview_ik','gripper','software_stop']);
function error(code){const e=new Error(code);e.code=code;return e;}
const delay=ms=>new Promise(r=>setTimeout(r,ms));
class WebRobotClient extends EventEmitter{
 constructor({url,jointLimits=DEFAULT_LIMITS,stateMaxAgeMs=750,now=Date.now,deferConnect=false}){
  super();const endpoint=new URL(url);
  if(!['ws:','wss:'].includes(endpoint.protocol)||endpoint.pathname!=='/ws')throw error('web_endpoint_invalid');
  this.now=now;this.jointLimits=jointLimits;this.stateMaxAgeMs=stateMaxAgeMs;
  this.last=null;this.receivedAt=0;this.pending=null;this.closed=false;this.ownerTag=null;
  this.url=endpoint.toString();this.socket=null;
  if(!deferConnect)this._open();
 }
 _open(){
  if(this.socket||this.closed)return;
  this.socket=new WebSocket(this.url);
  this.socket.on('message',raw=>this._message(raw));
  this.socket.on('error',()=>this._settle(error('web_transport_error')));
  this.socket.on('close',()=>{this.last=null;this._settle(error('web_disconnected'));this.emit('disconnected');});
 }
 _message(raw){
  let m;try{m=JSON.parse(raw);}catch{return;}
  if(m.type==='robot_state'){
   if(this.last&&Number(m.state_sequence)<=Number(this.last.state_sequence))return;
   this.last=m;this.receivedAt=this.now();this.emit('state',m);return;
  }
  const p=this.pending;if(!p)return;
  if(m.type==='error'&&(!m.request_id||m.request_id===p.id)){this._settle(error(m.code||m.reason||m.msg||'robot_error'));return;}
  if(m.request_id!==p.id)return;
  if(p.payload.cmd==='preview_ik'&&m.type==='ik_preview'){
   if(m.ok!==true||!validateJoints(m.joints_deg,this.jointLimits)){this._settle(error('ik_invalid'));return;}
   this._settle(null,m);return;
  }
  if(m.type!=='command_status'||m.status!=='complete')return;
  if(p.payload.cmd==='software_stop'){
   this._settle(m.stopped===true?null:error('stop_unconfirmed'),m);return;
  }
  if(m.robot_healthy===false){this._settle(error('feedback_invalid'));return;}
  try{this.state();}catch(e){this._settle(e);return;}
  if(m.reached!==true&&!(p.payload.cmd==='gripper'&&p.payload.position===0)){
   this._settle(error('target_not_reached'));return;
  }
  this.emit('completion',m);this._settle(null,m);
 }
 _settle(e,value){
  const p=this.pending;if(!p)return;this.pending=null;
  clearTimeout(p.timer);clearInterval(p.watchdog);
  if(e)p.reject(e);else p.resolve(value);
 }
 state({idle=false}={}){
  const m=this.last;if(!m||m.connected!==true||m.healthy!==true)throw error('feedback_invalid');
  if(this.now()-this.receivedAt>this.stateMaxAgeMs)throw error('feedback_stale');
  if(!Number.isSafeInteger(m.state_sequence)||!validateJoints(m.joints_deg,this.jointLimits)||
   !vector(m.flange_position_m)||!vector(m.flange_euler_rad)||!Number.isFinite(m.gripper_width_m))throw error('feedback_invalid');
  if(idle&&(m.moving===true||m.stateName!=='IDLE'))throw error('robot_not_stationary');
  return {...m,observedAtMs:this.receivedAt,jointsDeg:[...m.joints_deg],stateFresh:true,motionActive:m.moving===true};
 }
 async ready(timeoutMs=5000){
  this._open();
  const until=this.now()+timeoutMs;while(this.now()<until&&!this.closed){
   if(this.socket.readyState===WebSocket.OPEN){try{return this.state({idle:true});}catch{}}
   await delay(20);
  }throw error('robot_not_ready');
 }
 async command(payload,timeoutMs=15000){
  if(!ALLOWED.has(payload?.cmd))throw error('command_forbidden');
  if(this.pending)throw error('command_in_flight');
  if(this.closed||this.socket?.readyState!==WebSocket.OPEN)throw error('web_disconnected');
  if(payload.cmd!=='software_stop')this.state({idle:true});
  if(payload.cmd==='servo'&&!validateJoints(payload.joints,this.jointLimits))throw error('joint_limit');
  if(['move_l','preview_ik'].includes(payload.cmd)&&(!vector(payload.position)||!vector(payload.euler)))throw error('pose_invalid');
  if(payload.cmd==='gripper'&&(!Number.isFinite(payload.position)||payload.position<0||payload.position>1))throw error('gripper_invalid');
  if(!Number.isFinite(timeoutMs)||timeoutMs<=0||timeoutMs>45000)throw error('timeout_invalid');
  const id=payload.request_id||randomUUID();const outgoing={...payload,request_id:id,source:this.ownerTag||'web-grasp'};
  return new Promise((resolve,reject)=>{
   const p={id,payload:outgoing,resolve,reject};this.pending=p;
   const unsafe=code=>{if(this.pending!==p)return;const moving=['move_l','servo'].includes(outgoing.cmd);this._settle(error(code));
    if(moving)this.stop().catch(()=>{});};
   p.timer=setTimeout(()=>unsafe('command_timeout'),timeoutMs);
   if(outgoing.cmd!=='software_stop')p.watchdog=setInterval(()=>{try{this.state();}catch(e){unsafe(e.code);}},Math.min(100,this.stateMaxAgeMs/3));
   this.emit('command',outgoing);
   this.socket.send(JSON.stringify(outgoing),e=>{if(e&&this.pending===p)unsafe('web_send_failed');});
  });
 }
 preview(pose){return this.command({cmd:'preview_ik',position:pose.position,euler:pose.euler},5000);}
 async stop(){
  this.lastStopAt=this.now();
  if(this.pending?.payload.cmd==='software_stop')throw error('stop_in_flight');
  if(this.pending)this._settle(error('operator_stop'));
  const r=await this.command({cmd:'software_stop'},5000);return {...r,status:r.stopped?'interrupted':'uncertain'};
 }
 async execute(primitive){
  const p=primitive?.parameters,robot=this.state({idle:true});
  if(primitive.operation!=='vision.align.step'||!vector(p?.startJointsDeg,6)||!validateJoints(p.targetJointsDeg,this.jointLimits))throw error('alignment_invalid');
  if(robot.joints_deg.some((x,i)=>Math.abs(x-p.startJointsDeg[i])>0.5))throw error('alignment_start_changed');
  const indices=p.tier==='wrist'?[3,4,5]:p.tier==='arm_fallback'?[0,1,2]:[];
  if(!indices.length||p.targetJointsDeg.some((x,i)=>Math.abs(x-p.startJointsDeg[i])>(indices.includes(i)?(p.tier==='wrist'?4:2):1e-8)))throw error('alignment_step_invalid');
  const r=await this.command({cmd:'servo',joints:p.targetJointsDeg,request_id:primitive.primitiveId},p.timeoutMs||5000);
  const after=this.state({idle:true});
  if(after.joints_deg.some((x,i)=>Math.abs(x-p.targetJointsDeg[i])>0.8))throw error('alignment_not_reached');
  return {status:r.reached?'completed':'failed',primitiveId:primitive.primitiveId};
 }
 close(){if(this.closed)return;this.closed=true;this._settle(error('web_client_closed'));this.socket?.close();}
}
module.exports={WebRobotClient};
