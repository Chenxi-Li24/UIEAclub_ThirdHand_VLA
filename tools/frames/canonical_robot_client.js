'use strict';
// Opt-in transport for this isolated deployment. Construction opens no socket;
// only connect() subscribes/handshakes. Tests use local synthetic transports.
const {RobotWebSocketClient}=require('../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/robot_ws_client');
const {loadPolicy,normalizeRobotState,canonicalMoveToSdkTool}=require('./robot_frame_normalization');
const SERVER_ONLY_COMMANDS=new Set(['preview_ik','follow_start','follow_target','follow_stop',
  'teach_start','teach_hold','teach_keepalive']);
const TEACH_COMMANDS=new Set(['teach_start','teach_hold','teach_keepalive']);
const {randomUUID}=require('node:crypto');

function freeze(value){
  if(value&&typeof value==='object'){
    Object.values(value).forEach(freeze);Object.freeze(value);
  }
  return value;
}

class CanonicalRobotWebSocketClient extends RobotWebSocketClient{
  #policy;
  constructor({framePolicyPath,...options}={}){
    const policy=freeze(loadPolicy(framePolicyPath));
    super(options);
    this.teachActive=false;
    this.teachSupported=false;
    this.teachRequests=new Map();
    this.validatedSinceConnection=false;
    this.bootstrapResyncUsed=false;
    this.streamId=null;
    this.on('protocol',event=>{this.streamId=event.ready===true?randomUUID():null;});
    this.on('connection',event=>{
      if(event.connected===false){
        this.streamId=null;
        this.robotState=null;this.teachActive=false;
        this.validatedSinceConnection=false;this.bootstrapResyncUsed=false;
        for(const pending of [...this.teachRequests.values()])pending.finish(new Error('robot_disconnected'));
      }
    });
    this.#policy=policy;
    Object.defineProperty(this,'framePolicyId',{enumerable:true,get:()=>this.#policy.id});
  }
  _onMessage(raw){
    let message;
    try{message=JSON.parse(raw.toString());}
    catch{return super._onMessage(raw);}
    if(message?.type==='capability_response')this.teachSupported=
      [...TEACH_COMMANDS].every(command=>message.commands?.includes(command));
    if(this.protocolReady&&message?.type==='teach_state'){
      this.teachActive=message.active===true;
      const pending=this.teachRequests.get(message.request_id);
      if(pending?.command==='teach_start'&&message.active===true)pending.finish(null,message);
      return;
    }
    const pending=this.teachRequests.get(message?.request_id);
    if(pending){
      if(message.type==='error'){pending.finish(new Error(message.msg||message.message||message.code||'teach_failed'));return;}
      if(message.type==='command_status'&&message.command===pending.command){
        if(pending.command==='teach_keepalive'&&message.status==='accepted')pending.finish(null,message);
        if(pending.command==='teach_hold'&&message.status==='complete'){
          if(message.reached!==true)pending.finish(new Error('teach_hold_unconfirmed'));
          else {this.teachActive=false;pending.finish(null,message);}
        }
        return;
      }
    }
    // The live service additionally advertises a read-only IK preview. Keep
    // the original six-command client contract and every identity/stop check;
    // do not expose preview_ik (or any unknown command) through send().
    if(message?.type==='capability_response'&&Array.isArray(message.commands)&&
        message.commands.some(command=>SERVER_ONLY_COMMANDS.has(command))){
      return super._onMessage(Buffer.from(JSON.stringify({...message,
        commands:message.commands.filter(command=>!SERVER_ONLY_COMMANDS.has(command))})));
    }
    return super._onMessage(raw);
  }
  _normalizeState(message){
    let normalized;
    try{normalized=normalizeRobotState(message,this.#policy);}
    catch{this.robotState=null;return null;}
    const state=super._normalizeState(normalized);
    if(state===null){
      this.robotState=null;
      // A server subscribed before hardware connection can advertise its last
      // (idle) producer timestamp. Re-handshake ONCE when the stream starts.
      // Never accept this frame, change its timestamp, or relax age validation.
      const age=this._sourceAgeMs(Number(this.nowNs()),normalized.producer_monotonic_ns);
      if(!this.validatedSinceConnection&&!this.bootstrapResyncUsed&&this.protocolReady&&
          normalized.state_sequence>this.lastStateSequence&&Number.isFinite(age)&&
          Math.abs(age)>this.maxStateAgeMs&&this.ws?.readyState===this.WebSocketImpl.OPEN){
        this.bootstrapResyncUsed=true;this.protocolReady=false;
        this.handshakeNonce=this.nonceFactory();
        try{this.ws.send(JSON.stringify({type:'capability_request',
          schema:'thirdhand-robot-capability-v1',nonce:this.handshakeNonce}));}
        catch{this.handshakeNonce=null;}
      }
      return null;
    }
    this.validatedSinceConnection=true;
    if(!this.streamId)this.streamId=randomUUID();
    if(typeof message.teach_active==='boolean')this.teachActive=message.teach_active;
    return Object.freeze({...state,streamId:this.streamId,framePolicyId:this.#policy.id,
      frameNormalization:freeze({policyId:this.#policy.id,sourcePoseFrame:'sdk_tool',
        destinationPoseFrame:'robot_flange'}),
      sdkToolPose:freeze({positionM:[...normalized.sdk_tool_pose.position_m],
        eulerRad:[...normalized.sdk_tool_pose.euler_rad]})});
  }
  send(command){
    if(command?.cmd!=='move_l')return super.send(command);
    const state=this.getRobotState();
    if(state?.connected!==true||state.healthy!==true||state.stationary!==true||
        state.stateFresh!==true||state.framePolicyId!==this.#policy.id)return false;
    let wire;
    try{wire=canonicalMoveToSdkTool(command,this.#policy);}
    catch{return false;}
    return super.send(wire);
  }
  sendTeachCommand(command){
    if(!command||!TEACH_COMMANDS.has(command.cmd)||typeof command.request_id!=='string'||
        !command.request_id||this.protocolReady!==true||!this.ws||
        !this.teachSupported||this.ws.readyState!==this.WebSocketImpl.OPEN)
      return Promise.reject(new Error('teach_service_unavailable'));
    if(this.teachRequests.has(command.request_id))return Promise.reject(new Error('teach_request_pending'));
    return new Promise((resolve,reject)=>{
      const finish=(error,result)=>{
        clearTimeout(timer);this.teachRequests.delete(command.request_id);
        if(error)reject(error);else resolve({accepted:true,...result});
      };
      const timer=setTimeout(()=>finish(new Error('teach_ack_timeout')),4000);
      this.teachRequests.set(command.request_id,{command:command.cmd,finish});
      try{this.ws.send(JSON.stringify({...command}));}catch(error){finish(error);}
    });
  }
  getRobotState(){const state=super.getRobotState();return state?{...state,teachActive:this.teachActive,teachSupported:this.teachSupported}:null;}
}
module.exports={CanonicalRobotWebSocketClient};
