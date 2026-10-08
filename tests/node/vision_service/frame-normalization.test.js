'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {WebSocketServer}=require('ws');
const {mapState}=require('../../../services/vision/src/robot-state-relay');
const {startReader}=require('../../../services/vision/src/frames/robot_reader');
const {loadPolicy}=require('../../../services/vision/src/frames/robot_frame_normalization');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const policy={schema:'thirdhand-robot-frame-policy-v1',id:'sha256:'+'a'.repeat(64),
  source_semantics:'sdk_tool_mislabeled_as_robot_flange',
  T_flange_sdk_tool:[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]]};
const state=(euler=[0,0,0],position=[.3,0,.2])=>({type:'robot_state',connected:true,healthy:true,moving:false,
  pose_frame:'robot_flange',state_sequence:1,producer_monotonic_ns:1_000_000_000,
  flange_position_m:position,flange_euler_rad:euler,joints_deg:[0,0,0,0,0,0],velocities_deg_s:[0,0,0,0,0,0]});
test('relay removes the configured SDK tool translation in the rotated frame',()=>{
  const m=mapState(state([0,0,Math.PI/2],[.3,.17334,.2]),1_000_000_000,policy);
  assert.ok(m);assert.ok(Math.abs(m.flange_position_m[0]-.3)<1e-10);
  assert.ok(Math.abs(m.flange_position_m[1])<1e-10);
  assert.equal(m.frame_normalization.policy_id,policy.id);
});
test('relay rejects double conversion and missing explicit frame policy',()=>{
  assert.equal(mapState(state(),1_000_000_000,null),null);
  assert.equal(mapState({...state(),frame_normalization:{policy_id:policy.id}},1_000_000_000,policy),null);
});
test('relay still rejects stale feedback after frame normalization',()=>{
  assert.equal(mapState(state(),1_300_000_001,policy),null);
});
test('handeye reader emits canonical flange state without sending any command',async()=>{
  const server=new WebSocketServer({port:0});await new Promise(r=>server.once('listening',r));
  let commands=0;server.on('connection',s=>{s.on('message',()=>commands++);s.send(JSON.stringify(state()));});
  let reader;try{
    const received=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('state_timeout')),2000);
      reader=startReader(`ws://127.0.0.1:${server.address().port}`,m=>{clearTimeout(timer);resolve(m)},{policy});
    });
    assert.ok(Math.abs(received.flange_position_m[0]-.12666)<1e-10);
    assert.equal(received.pose_frame,'robot_flange');
    assert.equal(received.frame_normalization.policy_id,policy.id);
    assert.equal(commands,0);
  }finally{reader?.close();for(const s of server.clients)s.terminate();await new Promise(r=>server.close(r));}
});
test('policy loader rejects changed SDK configuration before any socket opens',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'frame-policy-test-'));
  const sdk=path.join(root,'sdk.yaml'),filename=path.join(root,'policy.json');
  fs.writeFileSync(sdk,'kinematics:\n  tool:\n    xyz: [0.17334,0,0]\n    rpy: [0,0,0]\n');
  const raw=fs.readFileSync(sdk);
  const config={...policy,sdk_config_path:sdk,bindings:[{path:sdk,sha256:crypto.createHash('sha256').update(raw).digest('hex')}]};
  delete config.id;fs.writeFileSync(filename,JSON.stringify(config));
  assert.ok(loadPolicy(filename).id.startsWith('sha256:'));
  fs.appendFileSync(sdk,'# changed\n');
  assert.throws(()=>loadPolicy(filename),/frame_policy_source_changed/);
});
test('policy loader refuses missing bindings and mismatched tool configuration',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'frame-policy-test-'));
  const sdk=path.join(root,'sdk.yaml'),filename=path.join(root,'policy.json');
  fs.writeFileSync(sdk,'kinematics:\n  tool:\n    xyz: [0.15,0,0]\n    rpy: [0,0,0]\n');
  const config={...policy,sdk_config_path:sdk,bindings:[]};delete config.id;
  fs.writeFileSync(filename,JSON.stringify(config));
  assert.throws(()=>loadPolicy(filename),/frame_policy_bindings_required/);
  config.bindings=[{path:sdk,sha256:crypto.createHash('sha256').update(fs.readFileSync(sdk)).digest('hex')}];
  fs.writeFileSync(filename,JSON.stringify(config));
  assert.throws(()=>loadPolicy(filename),/sdk_tool_policy_mismatch/);
});
test('policy loader rejects a changed producer source binding',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'frame-policy-test-'));
  const sdk=path.join(root,'sdk.yaml'),source=path.join(root,'producer.js'),filename=path.join(root,'policy.json');
  fs.writeFileSync(sdk,'kinematics:\n  tool:\n    xyz: [0.17334,0,0]\n    rpy: [0,0,0]\n');
  fs.writeFileSync(source,'// baseline producer\n');
  const config={...policy,sdk_config_path:sdk,bindings:[sdk,source].map(p=>({path:p,sha256:crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')}))};delete config.id;
  fs.writeFileSync(filename,JSON.stringify(config));assert.ok(loadPolicy(filename).id);
  fs.appendFileSync(source,'// changed\n');assert.throws(()=>loadPolicy(filename),/frame_policy_source_changed/);
});
