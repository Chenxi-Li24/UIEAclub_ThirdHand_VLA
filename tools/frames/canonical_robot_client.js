'use strict';
// Opt-in transport for this isolated deployment. Construction opens no socket;
// only connect() subscribes/handshakes. Tests use local synthetic transports.
const {RobotWebSocketClient}=require('../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/adapters/robot_ws_client');
const {loadPolicy,normalizeRobotState,canonicalMoveToSdkTool}=require('./robot_frame_normalization');

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
    this.#policy=policy;
    Object.defineProperty(this,'framePolicyId',{enumerable:true,get:()=>this.#policy.id});
  }
  _onMessage(raw){
    let message;
    try{message=JSON.parse(raw.toString());}
    catch{return super._onMessage(raw);}
    // The live service additionally advertises a read-only IK preview. Keep
    // the original six-command client contract and every identity/stop check;
    // do not expose preview_ik (or any unknown command) through send().
    if(message?.type==='capability_response'&&Array.isArray(message.commands)&&
        message.commands.length===7&&new Set(message.commands).size===7&&
        message.commands.includes('preview_ik')){
      return super._onMessage(Buffer.from(JSON.stringify({...message,
        commands:message.commands.filter(command=>command!=='preview_ik')})));
    }
    return super._onMessage(raw);
  }
  _normalizeState(message){
    let normalized;
    try{normalized=normalizeRobotState(message,this.#policy);}
    catch{this.robotState=null;return null;}
    const state=super._normalizeState(normalized);
    if(state===null){this.robotState=null;return null;}
    return Object.freeze({...state,framePolicyId:this.#policy.id,
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
}
module.exports={CanonicalRobotWebSocketClient};
