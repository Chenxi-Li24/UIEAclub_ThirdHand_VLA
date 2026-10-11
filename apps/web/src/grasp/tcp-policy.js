'use strict';
const fs=require('node:fs'),path=require('node:path');
const {loadPolicy}=require('../../../../services/vision/src/frames/robot_frame_normalization');
// A code-only runtime change must not masquerade as a new physical calibration.
// Both original and runtime evidence stay hash-bound; all geometry stays identical.
function resolveTcpPolicy({runtimeFile,sourceFile=runtimeFile,sourceId=null}){
 const runtime=loadPolicy(runtimeFile),source=loadPolicy(sourceFile);
 if(sourceId&&source.id!==sourceId)throw Error('tcp_source_policy_hash_mismatch');
 if(runtime.id===source.id)return {sourceId:source.id,runtimeId:runtime.id};
 const code=new Set(['robot-controller.js','startouch_bridge.py','startouch-bridge.js','joint_speed_policy.py','continuous_follow.py']);
 const immutable=p=>p.bindings.filter(b=>!code.has(path.basename(b.path))).map(b=>({path:fs.realpathSync(b.path),sha256:b.sha256}))
  .sort((a,b)=>a.path.localeCompare(b.path));
 const a=immutable(source),b=immutable(runtime);
 if(runtime.rebinding?.source_policy_id!==source.id||runtime.source_semantics!==source.source_semantics||
  JSON.stringify(runtime.T_flange_sdk_tool)!==JSON.stringify(source.T_flange_sdk_tool)||
  fs.realpathSync(runtime.sdk_config_path)!==fs.realpathSync(source.sdk_config_path)||
  !a.some(binding=>binding.path.endsWith('.urdf'))||JSON.stringify(a)!==JSON.stringify(b))throw Error('tcp_runtime_geometry_mismatch');
 return {sourceId:source.id,runtimeId:runtime.id};
}
module.exports={resolveTcpPolicy};
