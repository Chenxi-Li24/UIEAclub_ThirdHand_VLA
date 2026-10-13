'use strict';
const fs=require('node:fs'),path=require('node:path'),{createHash}=require('node:crypto');
const {loadPolicy}=require('../../../../services/vision/src/frames/robot_frame_normalization');
const code=new Set(['robot-controller.js','startouch_bridge.py','startouch-bridge.js','joint_speed_policy.py','continuous_follow.py']);
const immutable=p=>p.bindings.filter(b=>!code.has(path.basename(b.path))).map(b=>({path:fs.realpathSync(b.path),sha256:b.sha256}))
 .sort((a,b)=>a.path.localeCompare(b.path));
function verifyRelocation(source,runtime,filename,expectedId){
 if(typeof filename!=='string'||!/^sha256:[a-f0-9]{64}$/.test(expectedId||''))throw Error('tcp_rebinding_required');
 const bytes=fs.readFileSync(filename);
 if('sha256:'+createHash('sha256').update(bytes).digest('hex')!==expectedId)throw Error('tcp_rebinding_hash_mismatch');
 let certificate;try{certificate=JSON.parse(bytes);}catch{throw Error('tcp_rebinding_invalid');}
 if(certificate?.schema!=='thirdhand-tcp-policy-relocation-v1'||certificate.source_policy_id!==source.id||
  certificate.runtime_policy_id!==runtime.id||!Array.isArray(certificate.aliases))throw Error('tcp_rebinding_invalid');
 const fail=()=>{throw Error('tcp_runtime_geometry_mismatch');};
 if(runtime.source_semantics!==source.source_semantics||
  JSON.stringify(runtime.T_flange_sdk_tool)!==JSON.stringify(source.T_flange_sdk_tool))fail();
 const a=immutable(source),b=immutable(runtime),original=new Map(a.map(v=>[v.path,v])),current=new Map(b.map(v=>[v.path,v]));
 if(!a.some(v=>v.path.endsWith('.urdf'))||certificate.aliases.length!==a.length)fail();
 const aliases=new Map(),destinations=new Set();
 for(const alias of certificate.aliases){
  let from,to;
  try{from=fs.realpathSync(path.resolve(path.dirname(filename),alias.source));to=fs.realpathSync(path.resolve(path.dirname(filename),alias.runtime));}catch{fail();}
  if(!original.has(from)||!current.has(to)||aliases.has(from)||destinations.has(to)||
   path.basename(from)!==path.basename(to)||original.get(from).sha256!==current.get(to).sha256)fail();
  aliases.set(from,to);destinations.add(to);
 }
 if(a.some(v=>!aliases.has(v.path))||aliases.get(fs.realpathSync(source.sdk_config_path))!==fs.realpathSync(runtime.sdk_config_path))fail();
 // Added SDK evidence is still checked by loadPolicy. Conflicting copies of
 // any original geometry file are not permitted, even through a symlink.
 const names=p=>p.bindings.filter(v=>!code.has(path.basename(v.path)))
  .map(v=>({names:new Set([path.basename(v.path),path.basename(fs.realpathSync(v.path))]),sha256:v.sha256}));
 const originalNames=names(source);
 if(names(runtime).some(v=>originalNames.some(old=>old.sha256!==v.sha256&&[...v.names].some(name=>old.names.has(name)))))fail();
}
// A code-only runtime change must not masquerade as a new physical calibration.
// Both original and runtime evidence stay hash-bound; all geometry stays identical.
function resolveTcpPolicy({runtimeFile,sourceFile=runtimeFile,sourceId=null,rebindingFile=null,rebindingId=null}){
 const runtime=loadPolicy(runtimeFile),source=loadPolicy(sourceFile);
 if(sourceId&&source.id!==sourceId)throw Error('tcp_source_policy_hash_mismatch');
 if(rebindingFile!==null||rebindingId!==null){
  verifyRelocation(source,runtime,rebindingFile,rebindingId);
  return {sourceId:source.id,runtimeId:runtime.id};
 }
 if(runtime.id===source.id)return {sourceId:source.id,runtimeId:runtime.id};
 const a=immutable(source),b=immutable(runtime);
 if(runtime.rebinding?.source_policy_id!==source.id||runtime.source_semantics!==source.source_semantics||
  JSON.stringify(runtime.T_flange_sdk_tool)!==JSON.stringify(source.T_flange_sdk_tool)||
  fs.realpathSync(runtime.sdk_config_path)!==fs.realpathSync(source.sdk_config_path)||
  !a.some(binding=>binding.path.endsWith('.urdf'))||JSON.stringify(a)!==JSON.stringify(b))throw Error('tcp_runtime_geometry_mismatch');
 return {sourceId:source.id,runtimeId:runtime.id};
}
module.exports={resolveTcpPolicy};
