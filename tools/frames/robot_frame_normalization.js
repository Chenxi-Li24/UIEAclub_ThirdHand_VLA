'use strict';
// Pure pose conversion plus a content-bound configuration loader. No robot API.
const fs=require('node:fs'),crypto=require('node:crypto'),YAML=require('yaml');
const {validateRigidTransform,gripTargetToFlangePose,flangeToGripPose}=require('../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');
const hash=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function validatePolicy(policy){
  if(policy?.schema!=='thirdhand-robot-frame-policy-v1'||
      policy.source_semantics!=='sdk_tool_mislabeled_as_robot_flange'||
      !/^sha256:[a-f0-9]{64}$/.test(policy.id))throw Error('frame_policy_invalid');
  validateRigidTransform(policy.T_flange_sdk_tool);
  return policy;
}
function loadPolicy(filename){
  if(!filename)throw Error('frame_policy_required');
  const raw=fs.readFileSync(filename),policy=JSON.parse(raw);
  policy.id='sha256:'+hash(raw);validatePolicy(policy);
  if(!Array.isArray(policy.bindings)||!policy.bindings.length)throw Error('frame_policy_bindings_required');
  for(const binding of policy.bindings){
    if(hash(fs.readFileSync(binding.path))!==binding.sha256)throw Error('frame_policy_source_changed');
  }
  const tool=YAML.parse(fs.readFileSync(policy.sdk_config_path,'utf8')).kinematics.tool;
  // This migration is specifically for the observed translation-only SDK tool.
  if(!Array.isArray(tool.xyz)||tool.xyz.length!==3||!tool.xyz.every(Number.isFinite)||
      !Array.isArray(tool.rpy)||tool.rpy.length!==3||tool.rpy.some(v=>v!==0)||
      tool.xyz.some((v,i)=>Math.abs(v-policy.T_flange_sdk_tool[i][3])>1e-12)||
      policy.T_flange_sdk_tool.slice(0,3).some((row,i)=>row.slice(0,3).some((v,j)=>Math.abs(v-(i===j?1:0))>1e-12)))throw Error('sdk_tool_policy_mismatch');
  return policy;
}
function normalizeRobotState(message,policy){
  validatePolicy(policy);
  if(message?.type!=='robot_state'||message.pose_frame!=='robot_flange'||message.frame_normalization)throw Error('frame_source_or_double_conversion');
  const source={positionM:message.flange_position_m,eulerRad:message.flange_euler_rad};
  const flange=gripTargetToFlangePose(source,policy.T_flange_sdk_tool);
  const output={...message,flange_position_m:flange.positionM,flange_euler_rad:flange.eulerRad,
    sdk_tool_pose:{position_m:[...source.positionM],euler_rad:[...source.eulerRad]},
    frame_normalization:{policy_id:policy.id,source_pose_frame:'sdk_tool',destination_pose_frame:'robot_flange'}};
  // Legacy aliases carry SDK-tool coordinates and must not masquerade as flange.
  delete output.tcpPos;delete output.tcpEuler;
  return output;
}
function canonicalMoveToSdkTool(command,policy){
  validatePolicy(policy);
  if(!command||typeof command!=='object'||Array.isArray(command)||command.cmd!=='move_l'||
      !Number.isFinite(command.time_sec)||command.time_sec<=0||command.time_sec>30||
      (Object.hasOwn(command,'pose_frame')&&command.pose_frame!=='robot_flange')||
      (Object.hasOwn(command,'frame_policy_id')&&command.frame_policy_id!==policy.id)||
      Object.hasOwn(command,'frame_normalization'))throw Error('canonical_move_invalid');
  const pose=flangeToGripPose({positionM:command.position,eulerRad:command.euler},policy.T_flange_sdk_tool);
  const output={...command,position:pose.positionM,euler:pose.eulerRad};
  delete output.pose_frame;delete output.frame_policy_id;
  return output;
}
module.exports={loadPolicy,normalizeRobotState,canonicalMoveToSdkTool};
