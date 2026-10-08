'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { once } = require('node:events');
const { WebSocketServer } = require('ws');
const { mapState, startRelay } = require('../../../services/vision/src/robot-state-relay');
const policy={schema:'thirdhand-robot-frame-policy-v1',id:'sha256:'+'a'.repeat(64),
  source_semantics:'sdk_tool_mislabeled_as_robot_flange',
  T_flange_sdk_tool:[[1,0,0,.17334],[0,1,0,0],[0,0,1,0],[0,0,0,1]]};

const state = (now,sequence=1) => ({type:'robot_state',connected:true,healthy:true,
  moving:false,pose_frame:'robot_flange',state_sequence:sequence,
  producer_monotonic_ns:now,flange_position_m:[0.3,0,0.18],flange_euler_rad:[0,0,0],
  joints_deg:[0,0,0,0,0,0],velocities_deg_s:[0,0,0,0,0,0]});

test('maps fresh SDK tool telemetry into canonical flange without changing timestamp or units', () => {
  assert.deepEqual(mapState(state(1000000000),1000000010,policy),{
    type:'arm_state',pose_frame:'robot_flange',connected:true,healthy:true,stationary:true,motion_active:false,feedback_invalidated:false,
    flange_position_m:[0.12666,0,0.18],flange_euler_rad:[0,0,0],joints_deg:[0,0,0,0,0,0],
    frame_normalization:{policy_id:policy.id,source_pose_frame:'sdk_tool',destination_pose_frame:'robot_flange'},
    observed_monotonic_ns:1000000000});
});
test('rejects invalid stale future and unmeasured telemetry', () => {
  const now=1000000000;
  for (const patch of [{connected:false},{healthy:false},{pose_frame:'robot_tcp'},
    {producer_monotonic_ns:now-250000001},{producer_monotonic_ns:now+1},
    {producer_monotonic_ns:null},{state_sequence:NaN},{flange_position_m:new Array(3)},
    {joints_deg:[0,0,0,0,0,Infinity]},{velocities_deg_s:null},{moving:null}]) {
    assert.equal(mapState({...state(now),...patch},now,policy),null);
  }
});
test('moving or nonstationary telemetry cannot establish stationary geometry', () => {
  assert.equal(mapState({...state(100),moving:true},100,policy).stationary,false);
  assert.equal(mapState({...state(100),moving:true},100,policy).motion_active,true);
  assert.equal(mapState({...state(100),velocities_deg_s:[0,0,3,0,0,0]},100,policy).stationary,false);
  assert.equal(mapState({...state(100),velocities_deg_s:[0,0,3,0,0,0]},100,policy).motion_active,false);
});

test('real sockets forward only state, reject replay and invalidate on source disconnect', async t => {
  const robot = new WebSocketServer({host:'127.0.0.1',port:0});
  const vision = new WebSocketServer({host:'127.0.0.1',port:0});
  await Promise.all([once(robot,'listening'),once(vision,'listening')]);
  const robotConnection=once(robot,'connection'), visionConnection=once(vision,'connection');
  const relay=startRelay({robotUrl:`ws://127.0.0.1:${robot.address().port}`,
    visionUrl:`ws://127.0.0.1:${vision.address().port}`,policy});
  t.after(async()=>{relay.close(); for(const server of [robot,vision]) {
    for(const socket of server.clients)socket.terminate();
    await new Promise(resolve=>server.close(resolve));
  }});
  const [[r],[v]]=await Promise.all([robotConnection,visionConnection]);
  let robotCommands=0;
  r.on('message',()=>robotCommands++);
  const incoming=[];
  v.on('message',raw=>incoming.push(JSON.parse(raw)));
  const waitFor=async predicate=>{for(let n=0;n<100;n++){
    if(predicate())return;await new Promise(resolve=>setTimeout(resolve,10));
  }assert.fail('relay output timeout');};
  const clock=()=>Number(process.hrtime.bigint());
  r.send(JSON.stringify(state(clock(),1)));
  await waitFor(()=>incoming.length===1);
  assert.equal(incoming[0].stationary,true);
  r.send(JSON.stringify(state(clock(),1)));
  await waitFor(()=>incoming.length===2);
  assert.equal(incoming[1].stationary,false);
  assert.equal(incoming[1].feedback_invalidated,true);
  r.send(JSON.stringify(state(clock(),2)));
  await waitFor(()=>incoming.length===3);
  assert.equal(incoming[2].stationary,true);
  r.send('null');
  await waitFor(()=>incoming.length===4);
  assert.equal(incoming[3].stationary,false);
  r.send(JSON.stringify(state(clock(),3)));
  await waitFor(()=>incoming.length===5);
  assert.equal(incoming[4].stationary,true);
  r.close();
  await waitFor(()=>incoming.length===6);
  assert.equal(incoming[5].stationary,false);
  assert.equal(robotCommands,0);
});
