'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),crypto=require('node:crypto');
const {resolveTcpPolicy}=require('../../../apps/web/src/grasp/tcp-policy');
const hash=b=>crypto.createHash('sha256').update(b).digest('hex');
function fixture(t){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'grasp-policy-rebind-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const sdk=path.join(root,'robot_kinematics.yaml'),urdf=path.join(root,'arm.urdf');
 fs.writeFileSync(sdk,'kinematics:\n  tool:\n    xyz: [0.17334, 0, 0]\n    rpy: [0, 0, 0]\n');fs.writeFileSync(urdf,'unchanged robot');
 const original=path.join(root,'original'),runtime=path.join(root,'runtime');fs.mkdirSync(original);fs.mkdirSync(runtime);
 fs.writeFileSync(path.join(original,'robot-controller.js'),'original controller');fs.writeFileSync(path.join(runtime,'robot-controller.js'),'10 percent controller');
 const policy=controller=>({schema:'thirdhand-robot-frame-policy-v1',source_semantics:'sdk_tool_mislabeled_as_robot_flange',
  T_flange_sdk_tool:[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]],sdk_config_path:sdk,
  bindings:[sdk,urdf,controller].map(file=>({path:file,sha256:hash(fs.readFileSync(file))}))});
 const sourceFile=path.join(root,'source.json'),runtimeFile=path.join(root,'runtime.json');
 fs.writeFileSync(sourceFile,JSON.stringify(policy(path.join(original,'robot-controller.js'))));
 const sourceId='sha256:'+hash(fs.readFileSync(sourceFile)),next=policy(path.join(runtime,'robot-controller.js'));
 next.rebinding={source_policy_id:sourceId};fs.writeFileSync(runtimeFile,JSON.stringify(next));
 return {sourceFile,sourceId,runtimeFile,next,write(){fs.writeFileSync(runtimeFile,JSON.stringify(next));}};
}
test('a hash-bound code-only runtime rebind preserves the original measured TCP identity',t=>{
 const f=fixture(t);const binding=resolveTcpPolicy(f);
 assert.equal(binding.sourceId,f.sourceId);assert.notEqual(binding.runtimeId,f.sourceId);
});
test('runtime rebind rejects changed tool geometry, missing provenance, or changed immutable robot evidence',t=>{
 for(const mutate of [f=>f.next.T_flange_sdk_tool[0][3]=.18,
  f=>delete f.next.rebinding,f=>f.next.bindings=f.next.bindings.filter(b=>!b.path.endsWith('.urdf'))]){
  const f=fixture(t);mutate(f);f.write();assert.throws(()=>resolveTcpPolicy(f));
 }
});
