'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {EventEmitter}=require('node:events');
const {CanonicalRobotWebSocketClient}=require('./canonical_robot_client');
class Socket extends EventEmitter{
  static OPEN=1;
  constructor(url){super();this.url=url;this.readyState=1;this.sent=[];Socket.latest=this;}
  send(value){this.sent.push(JSON.parse(value));}
  close(){this.readyState=3;this.emit('close');}
}
function fixture(t,{connect=true,capability={}}={}){
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'canonical-client-test-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const sdk=path.join(root,'sdk.yaml'),filename=path.join(root,'policy.json');
  fs.writeFileSync(sdk,'kinematics:\n  tool:\n    xyz: [0.17334,0,0]\n    rpy: [0,0,0]\n');
  fs.writeFileSync(filename,JSON.stringify({schema:'thirdhand-robot-frame-policy-v1',
    source_semantics:'sdk_tool_mislabeled_as_robot_flange',sdk_config_path:sdk,
    T_flange_sdk_tool:[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
    bindings:[{path:sdk,sha256:crypto.createHash('sha256').update(fs.readFileSync(sdk)).digest('hex')}]}));
  let now=1_000_000_000n;
  const client=new CanonicalRobotWebSocketClient({WebSocketImpl:Socket,url:'ws://local-test-only/ws',
    framePolicyPath:filename,nowNs:()=>now});
  t.after(()=>client.shutdown());
  if(!connect)return{client,filename,sdk};
  client.connect();const socket=Socket.latest;socket.emit('open');
  const request=socket.sent.at(-1);
  socket.emit('message',Buffer.from(JSON.stringify({type:'capability_response',
    schema:'thirdhand-robot-capability-v1',nonce:request.nonce,
    protocol_version:'thirdhand-robot-lowlevel-v1',pose_frame:'robot_flange',
    commands:['move_l','move_joint','gripper','preset','software_stop','get_state'],
    correlated_completions:true,software_stop_ack:true,software_stop_state_boundary:true,
    state_units:{position:'m',orientation:'rad',joints:'deg',joint_velocity:'deg/s',gripper:'m'},
    state_stream:{sequence:'uint53',producer_monotonic_ns:'uint53',strictly_increasing:true},
    state_sequence:0,producer_monotonic_ns:999_999_900,...capability})));
  const state={type:'robot_state',connected:true,healthy:true,moving:false,
    state_sequence:1,producer_monotonic_ns:1_000_000_000,pose_frame:'robot_flange',
    flange_position_m:[.37334,.3,.4],flange_euler_rad:[0,0,0],
    joints_deg:[0,0,0,0,0,0],velocities_deg_s:[0,0,0,0,0,0],gripper_width_m:.06};
  const feedback=m=>socket.emit('message',Buffer.from(JSON.stringify(m)));
  feedback(state);
  return{client,socket,state,feedback,filename,sdk,setNow:value=>{now=value;}};
}
test('canonical client requires a content-bound SDK policy',()=>{
  assert.throws(()=>new CanonicalRobotWebSocketClient({WebSocketImpl:Socket,url:'ws://local-test-only/ws'}),/frame_policy_required/);
});
test('incoming SDK tool coordinates become true flange coordinates',t=>{
  const {client}=fixture(t),state=client.getRobotState();
  assert.deepEqual(state.flangePositionM,[.2,.3,.4]);
  assert.match(state.framePolicyId,/^sha256:[a-f0-9]{64}$/);
  assert.deepEqual(state.frameNormalization,{policyId:state.framePolicyId,
    sourcePoseFrame:'sdk_tool',destinationPoseFrame:'robot_flange'});
});
test('known server capability extensions keep canonical state read-only',t=>{
  const commands=['move_l','preview_ik','move_joint','gripper','preset','software_stop','get_state',
    'follow_start','follow_target','follow_stop'];
  const {client,socket}=fixture(t,{capability:{commands}}),count=socket.sent.length;
  assert.deepEqual(client.getRobotState().flangePositionM,[.2,.3,.4]);
  assert.equal(client.send({cmd:'follow_start',request_id:'forbidden'}),false);
  assert.equal(socket.sent.length,count);
});
test('outgoing flange target is converted to the configured SDK tool',t=>{
  const {client,socket}=fixture(t);
  assert.equal(client.send({cmd:'move_l',request_id:'one',position:[.2,.3,.4],euler:[0,0,0],time_sec:1}),true);
  assert.deepEqual(socket.sent.at(-1).position,[.37334,.3,.4]);
  assert.deepEqual(socket.sent.at(-1).euler,[0,0,0]);
});
test('tool translation rotates with the target flange orientation',t=>{
  const {client,socket}=fixture(t);
  assert.equal(client.send({cmd:'move_l',request_id:'yaw',position:[.2,.3,.4],euler:[0,0,Math.PI/2],time_sec:1}),true);
  assert.deepEqual(socket.sent.at(-1).position,[.2,.47334,.4]);
});
test('bad or already converted feedback invalidates cached canonical state',t=>{
  const {client,state,feedback}=fixture(t);
  feedback({...state,state_sequence:2,frame_normalization:{policy_id:'sha256:'+'a'.repeat(64)}});
  assert.equal(client.getRobotState(),null);
  assert.equal(client.send({cmd:'move_l',request_id:'bad',position:[.2,.3,.4],euler:[0,0,0],time_sec:1}),false);
});
test('stale feedback prevents a Cartesian target from being sent',t=>{
  const {client,socket,setNow}=fixture(t);setNow(1_250_000_001n);
  const count=socket.sent.length;
  assert.equal(client.send({cmd:'move_l',request_id:'stale',position:[.2,.3,.4],euler:[0,0,0],time_sec:1}),false);
  assert.equal(socket.sent.length,count);
});
test('SDK-frame or malformed targets are rejected without occupying a command slot',t=>{
  const {client,socket}=fixture(t),count=socket.sent.length;
  for(const change of [{pose_frame:'sdk_tool'},{position:[NaN,0,0]},{time_sec:0}]){
    assert.equal(client.send({cmd:'move_l',request_id:'bad',position:[.2,.3,.4],euler:[0,0,0],time_sec:1,...change}),false);
  }
  assert.equal(socket.sent.length,count);
  assert.equal(client.send({cmd:'get_state'}),true);
});
test('non-Cartesian low-level commands retain their existing payload',t=>{
  const {client,socket}=fixture(t),command={cmd:'get_state'};
  assert.equal(client.send(command),true);assert.deepEqual(socket.sent.at(-1),command);
});
test('construction is dormant and does not create a socket',t=>{
  const previous=Socket.latest,{client}=fixture(t,{connect:false});
  assert.equal(Socket.latest,previous);assert.equal(client.ws,null);
  assert.equal(client.getRobotState(),null);assert.equal(client.connected,false);
});
test('policy identity and returned SDK provenance cannot be mutated',t=>{
  const {client}=fixture(t),id=client.framePolicyId,state=client.getRobotState();
  assert.throws(()=>{client.framePolicyId='changed';},TypeError);
  assert.throws(()=>{state.sdkToolPose.positionM[0]=99;},TypeError);
  state.flangePositionM[0]=99;
  assert.equal(client.framePolicyId,id);
  assert.deepEqual(client.getRobotState().flangePositionM,[.2,.3,.4]);
});
test('replayed feedback clears canonical state and blocks motion',t=>{
  const {client,socket,state,feedback}=fixture(t),count=socket.sent.length;
  feedback({...state});assert.equal(client.getRobotState(),null);
  assert.equal(client.send({cmd:'move_l',request_id:'replay',position:[.2,.3,.4],euler:[0,0,0],time_sec:1}),false);
  assert.equal(socket.sent.length,count);
});
test('unhealthy, disconnected or moving feedback blocks Cartesian commands',t=>{
  const {client,socket,state,feedback}=fixture(t),count=socket.sent.length;
  let sequence=1;
  for(const change of [{healthy:false},{connected:false},{moving:true},{velocities_deg_s:[1,0,0,0,0,0]}]){
    sequence++;
    feedback({...state,state_sequence:sequence,producer_monotonic_ns:1_000_000_000+sequence,...change});
    assert.equal(client.send({cmd:'move_l',request_id:'unsafe',position:[.2,.3,.4],euler:[0,0,0],time_sec:1}),false);
  }
  assert.equal(socket.sent.length,count);assert.equal(client.inFlight,null);
});
test('wrong policy or double-converted targets never reach transport',t=>{
  const {client,socket}=fixture(t),count=socket.sent.length;
  for(const change of [{frame_policy_id:'sha256:'+'a'.repeat(64)},{frame_normalization:{}}]){
    assert.equal(client.send({cmd:'move_l',request_id:'wrong-policy',position:[.2,.3,.4],euler:[0,0,0],time_sec:1,...change}),false);
  }
  assert.equal(socket.sent.length,count);assert.equal(client.inFlight,null);
});
test('non-object and array command containers cannot bypass the base contract',t=>{
  const {client,socket}=fixture(t),count=socket.sent.length;
  const properties={cmd:'move_l',request_id:'container',position:[.2,.3,.4],euler:[0,0,0],time_sec:1};
  for(const command of [Object.assign([],properties),Object.assign(()=>{},properties)]){
    assert.equal(client.send(command),false);
  }
  assert.equal(socket.sent.length,count);assert.equal(client.inFlight,null);
});
test('live service readonly IK capability does not prevent canonical feedback',t=>{
  const {client,socket}=fixture(t,{capability:{commands:
    ['move_l','preview_ik','move_joint','gripper','preset','software_stop','get_state']}});
  assert.equal(client.protocolReady,true);
  assert.deepEqual(client.getRobotState()?.flangePositionM,[.2,.3,.4]);
  const count=socket.sent.length;
  assert.equal(client.send({cmd:'preview_ik',position:[.2,.3,.4],euler:[0,0,0]}),false);
  assert.equal(socket.sent.length,count);
  assert.equal(client.send({cmd:'get_state'}),true);
});
test('optional readonly IK does not admit unknown duplicate or missing capabilities',t=>{
  for(const commands of [
    ['move_l','preview_ik','move_joint','gripper','preset','software_stop','get_state','unknown_motion'],
    ['move_l','preview_ik','move_joint','gripper','preset','software_stop','preview_ik'],
    ['move_l','preview_ik','move_joint','gripper','preset','software_stop','unknown_motion'],
  ]){
    const {client,socket}=fixture(t,{capability:{commands}}),count=socket.sent.length;
    assert.equal(client.protocolReady,false);assert.equal(client.getRobotState(),null);
    assert.equal(client.send({cmd:'get_state'}),false);assert.equal(socket.sent.length,count);
  }
});
test('optional readonly IK never weakens identity correlation or stop proof',t=>{
  const commands=['move_l','preview_ik','move_joint','gripper','preset','software_stop','get_state'];
  for(const change of [{nonce:'wrong'},{pose_frame:'sdk_tool'},{protocol_version:'unknown'},
    {correlated_completions:false},{software_stop_ack:false},{software_stop_state_boundary:false}]){
    const {client,socket}=fixture(t,{capability:{commands,...change}}),count=socket.sent.length;
    assert.equal(client.protocolReady,false);assert.equal(client.getRobotState(),null);
    assert.equal(client.send({cmd:'get_state'}),false);assert.equal(socket.sent.length,count);
  }
});
