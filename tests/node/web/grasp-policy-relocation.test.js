'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {resolveTcpPolicy}=require('../../../apps/web/src/grasp/tcp-policy');
const digest=bytes=>'sha256:'+crypto.createHash('sha256').update(bytes).digest('hex');
const write=(file,value)=>fs.writeFileSync(file,JSON.stringify(value));
function fixture(t){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'tcp-relocation-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const original=path.join(root,'original'),generated=path.join(root,'generated');
 fs.mkdirSync(original);fs.mkdirSync(generated);
 const yaml='kinematics:\n  tool:\n    xyz: [0.17334, 0, 0]\n    rpy: [0, 0, 0]\n';
 for(const directory of [original,generated]){
  fs.writeFileSync(path.join(directory,'robot_kinematics.yaml'),yaml);
  fs.writeFileSync(path.join(directory,'arm.urdf'),'original physical geometry');
  fs.writeFileSync(path.join(directory,'robot-controller.js'),directory);
 }
 fs.writeFileSync(path.join(generated,'libstartouch.so'),'additional hash-bound SDK evidence');
 const policy=directory=>({schema:'thirdhand-robot-frame-policy-v1',
  source_semantics:'sdk_tool_mislabeled_as_robot_flange',
  T_flange_sdk_tool:[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
  sdk_config_path:path.join(directory,'robot_kinematics.yaml'),
  bindings:['robot_kinematics.yaml','arm.urdf','robot-controller.js'].map(name=>{
   const filename=path.join(directory,name);return {path:filename,sha256:digest(fs.readFileSync(filename)).slice(7)};
  })});
 const sourceFile=path.join(root,'source.json'),runtimeFile=path.join(root,'runtime.json');
 const source=policy(original),runtime=policy(generated);
 runtime.bindings.push({path:path.join(generated,'libstartouch.so'),sha256:digest(fs.readFileSync(path.join(generated,'libstartouch.so'))).slice(7)});
 // This is the repository policy ancestry, not the measured TCP's source ID.
 runtime.rebinding={source_policy_id:'sha256:'+'d'.repeat(64)};
 write(sourceFile,source);write(runtimeFile,runtime);
 const sourceId=digest(fs.readFileSync(sourceFile));
 const certificate={schema:'thirdhand-tcp-policy-relocation-v1',source_policy_id:sourceId,
  runtime_policy_id:digest(fs.readFileSync(runtimeFile)),aliases:['robot_kinematics.yaml','arm.urdf'].map(name=>({source:path.join(original,name),runtime:path.join(generated,name)}))};
 const rebindingFile=path.join(root,'tcp-relocation.json');
 const f={sourceFile,runtimeFile,sourceId,rebindingFile,source,runtime,certificate,original,generated,
  seal(){write(runtimeFile,runtime);certificate.runtime_policy_id=digest(fs.readFileSync(runtimeFile));write(rebindingFile,certificate);this.rebindingId=digest(fs.readFileSync(rebindingFile));}};
 f.seal();return f;
}
test('explicit hash-bound relocation retains measured TCP identity across identical geometry copies',t=>{
 const f=fixture(t),result=resolveTcpPolicy(f);
 assert.equal(result.sourceId,f.sourceId);
 assert.equal(result.runtimeId,digest(fs.readFileSync(f.runtimeFile)));
 assert.notEqual(result.sourceId,result.runtimeId);
});
test('relocation is never inferred without the explicit certificate',t=>{
 const f=fixture(t);delete f.rebindingFile;delete f.rebindingId;
 assert.throws(()=>resolveTcpPolicy(f),/tcp_runtime_geometry_mismatch/);
});
test('certificate bytes and both referenced policy identities must stay bound',t=>{
 for(const mutate of [
  f=>{f.rebindingId='sha256:'+'f'.repeat(64);},
  f=>{f.certificate.source_policy_id='sha256:'+'e'.repeat(64);f.seal();},
  f=>{f.certificate.runtime_policy_id='sha256:'+'e'.repeat(64);write(f.rebindingFile,f.certificate);f.rebindingId=digest(fs.readFileSync(f.rebindingFile));},
  f=>{delete f.rebindingId;},
  f=>{f.certificate.schema='unknown';f.seal();},
 ]){const f=fixture(t);mutate(f);assert.throws(()=>resolveTcpPolicy(f),/tcp_rebinding_/);}
});
test('relocation requires complete unique source evidence and bound matching destination paths',t=>{
 for(const mutate of [
  f=>f.certificate.aliases.pop(),
  f=>f.certificate.aliases.push(f.certificate.aliases[0]),
  f=>f.certificate.aliases[1].runtime=f.certificate.aliases[0].runtime,
  f=>f.certificate.aliases[1].source=path.join(f.original,'robot-controller.js'),
  f=>{const unbound=path.join(f.generated,'unbound.urdf');fs.copyFileSync(path.join(f.generated,'arm.urdf'),unbound);f.certificate.aliases[1].runtime=unbound;},
 ]){const f=fixture(t);mutate(f);f.seal();assert.throws(()=>resolveTcpPolicy(f),/tcp_runtime_geometry_mismatch/);}
});
test('resealing cannot authorize different geometry or a conflicting copy of a required file',t=>{
 for(const mutate of [
  f=>{const p=path.join(f.generated,'arm.urdf');fs.writeFileSync(p,'different physical geometry');f.runtime.bindings.find(b=>b.path===p).sha256=digest(fs.readFileSync(p)).slice(7);},
  f=>{const dir=path.join(f.generated,'conflict');fs.mkdirSync(dir);const p=path.join(dir,'arm.urdf');fs.writeFileSync(p,'different robot');f.runtime.bindings.push({path:p,sha256:digest(fs.readFileSync(p)).slice(7)});},
  f=>{const dir=path.join(f.generated,'symlink-conflict');fs.mkdirSync(dir);const target=path.join(dir,'changed-geometry.txt');fs.writeFileSync(target,'different robot');const p=path.join(dir,'arm.urdf');fs.symlinkSync(target,p);f.runtime.bindings.push({path:p,sha256:digest(fs.readFileSync(p)).slice(7)});},
  f=>{for(const directory of [f.original,f.generated]){fs.renameSync(path.join(directory,'arm.urdf'),path.join(directory,'physical.urdf'));fs.symlinkSync(path.join(directory,'physical.urdf'),path.join(directory,'arm.urdf'));}const dir=path.join(f.generated,'cross-name-conflict');fs.mkdirSync(dir);const target=path.join(dir,'changed-geometry.txt');fs.writeFileSync(target,'different robot');const p=path.join(dir,'physical.urdf');fs.symlinkSync(target,p);f.runtime.bindings.push({path:p,sha256:digest(fs.readFileSync(p)).slice(7)});},
  f=>{f.runtime.T_flange_sdk_tool[0][3]=.18;const p=f.runtime.sdk_config_path;fs.writeFileSync(p,'kinematics:\n  tool:\n    xyz: [0.18, 0, 0]\n    rpy: [0, 0, 0]\n');f.runtime.bindings.find(b=>b.path===p).sha256=digest(fs.readFileSync(p)).slice(7);},
  f=>{f.runtime.sdk_config_path=f.source.sdk_config_path;},
 ]){const f=fixture(t);mutate(f);f.seal();assert.throws(()=>resolveTcpPolicy(f),/tcp_runtime_geometry_mismatch/);}
});
test('all original and additional runtime provenance is still verified against actual bytes',t=>{
 for(const filename of ['original/arm.urdf','generated/libstartouch.so']){
  const f=fixture(t);fs.appendFileSync(path.join(path.dirname(f.sourceFile),filename),'changed');
  assert.throws(()=>resolveTcpPolicy(f),/frame_policy_source_changed/);
 }
});
test('invalid explicit certificate is not silently ignored for an unchanged policy',t=>{
 const f=fixture(t);f.runtimeFile=f.sourceFile;f.rebindingId='sha256:'+'f'.repeat(64);
 assert.throws(()=>resolveTcpPolicy(f),/tcp_rebinding_/);
});
test('grasp configuration consumes the relocation certificate and preserves the active measured candidate',async t=>{
 const f=fixture(t),root=path.dirname(f.sourceFile);
 const {TcpCalibrationArtifactStore}=require('../../../apps/web/src/tcp-calibration/artifact-store');
 const store=new TcpCalibrationArtifactStore({root:path.join(root,'tcp-artifacts')});
 const matrix=[[1,0,0,.09826448704090089],[0,1,0,-.006341722837237676],[0,0,1,-.0013153436560723233],[0,0,0,1]];
 const candidate=store.finalizePending({schema:'thirdhand-tcp-calibration-session-v1',sessionId:'measured',revision:1,
  stage:'ready_to_finalize',framePolicyId:f.sourceId,solveReport:{accepted:true},validationReport:{accepted:true},
  derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1',T_flange_grasp_tcp:matrix}});
 store.activate({candidateId:candidate.candidateId,expectedActiveId:null});
 const calibrationFile=path.join(root,'calibration.json');
 write(calibrationFile,{numerically_validated:true,frame_normalization:{policy_id:f.certificate.runtime_policy_id},
  T_flange_camera:{matrix_4x4:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]},camera:{}});
 const config={...require('../../../apps/web/configs/web-grasp.json'),
  framePolicyFile:f.runtimeFile,framePolicyId:f.certificate.runtime_policy_id,
  calibrationFile,calibrationId:digest(fs.readFileSync(calibrationFile)),
  tcpSourceFramePolicyFile:f.sourceFile,tcpSourceFramePolicyId:f.sourceId,
  tcpPolicyRebindingFile:f.rebindingFile,tcpPolicyRebindingId:f.rebindingId};
 const configDir=path.join(root,'apps/web/configs');fs.mkdirSync(configDir,{recursive:true});
 const configFile=path.join(configDir,'web-grasp.json');write(configFile,config);
 const controller=require('../../../apps/web/src/grasp').createFromFile(configFile,{tcpStore:store});
 t.after(()=>controller.close());
 const tcp=controller.tcpConfiguration();
 assert.equal(tcp.id,candidate.candidateId);assert.equal(tcp.source,'measured');
 assert.equal(tcp.framePolicyId,f.sourceId);assert.equal(tcp.runtimeFramePolicyId,f.certificate.runtime_policy_id);
 assert.deepEqual(tcp.T_flange_grasp_tcp,matrix);assert.equal(controller.status().active,false);
});
