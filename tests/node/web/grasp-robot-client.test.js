'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {WebSocketServer}=require('ws');
const {WebRobotClient}=require('../../../apps/web/src/grasp/robot-client');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const limits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];
function robot(sequence=1){return {type:'robot_state',connected:true,healthy:true,moving:false,stateName:'IDLE',
 state_sequence:sequence,producer_monotonic_ns:sequence*1000000,joints_deg:[0,0,-1,0,0,0],
 flange_position_m:[0.3,0,0.2],flange_euler_rad:[0,0,0],gripper_width_m:0.03};}
async function setup(t,onCommand,options={}){
 const wss=new WebSocketServer({port:0});await new Promise(r=>wss.once('listening',r));let upstream,seq=0;
 const received=[];const intervals=[];
 wss.on('connection',s=>{upstream=s;s.send(JSON.stringify(robot(++seq)));const timer=setInterval(()=>{if(s.readyState===1)s.send(JSON.stringify(robot(++seq)));},10);intervals.push(timer);
  s.on('message',b=>{const m=JSON.parse(b);received.push(m);onCommand?.(s,m);});});
 const client=new WebRobotClient({url:`ws://127.0.0.1:${wss.address().port}/ws`,jointLimits:limits,stateMaxAgeMs:100,...options});
 t.after(async()=>{client.close();for(const i of intervals)clearInterval(i);for(const s of wss.clients)s.terminate();await new Promise(r=>wss.close(r));});
 await client.ready();return {client,received,stopFrames:()=>intervals.forEach(clearInterval),socket:()=>upstream};
}
test('accepted and unrelated completion never substitute for correlated arrival',async t=>{
 const {client,received}=await setup(t,(s,m)=>{
  s.send(JSON.stringify({type:'command_status',status:'accepted',request_id:m.request_id}));
  s.send(JSON.stringify({type:'command_status',status:'complete',request_id:'other',reached:true}));
  setTimeout(()=>s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,reached:true,robot_healthy:true})),30);
 });let done=false;const p=client.command({cmd:'gripper',position:1},300).then(()=>done=true);
 await sleep(15);assert.equal(done,false);await p;assert.equal(done,true);
 assert.deepEqual(received.map(m=>m.cmd),['gripper']);
});
test('IK output is checked against hard bounds before being returned',async t=>{
 const {client}=await setup(t,(s,m)=>s.send(JSON.stringify({type:'ik_preview',request_id:m.request_id,ok:true,joints_deg:[0,0,1,0,0,0]})));
 await assert.rejects(client.preview({position:[0.3,0,0.2],euler:[0,0,0]}),/ik_invalid/);
});
test('fresh feedback is required and idle client close never toggles native connection',async t=>{
 const {client,received,stopFrames}=await setup(t);stopFrames();await sleep(130);
 await assert.rejects(client.command({cmd:'gripper',position:1}),/feedback_stale/);
 client.close();assert.deepEqual(received,[]);
});
test('failed motion completion is not an authorization for the next command',async t=>{
 const {client}=await setup(t,(s,m)=>s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,reached:false,robot_healthy:true})));
 await assert.rejects(client.command({cmd:'move_l',position:[0.31,0,0.2],euler:[0,0,0]}),/target_not_reached/);
});
test('gripper zero contact can be reported without falsifying reached flag',async t=>{
 const {client}=await setup(t,(s,m)=>s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,reached:false,actual_width_m:0.03,robot_healthy:true})));
 const r=await client.command({cmd:'gripper',position:0});assert.equal(r.reached,false);assert.equal(r.actual_width_m,0.03);
});
test('lost feedback during motion sends one web software stop and terminates',async t=>{
 const {client,received,stopFrames}=await setup(t,(s,m)=>{if(m.cmd==='software_stop')s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,stopped:true}));});
 const p=client.command({cmd:'move_l',position:[0.31,0,0.2],euler:[0,0,0]},1000);stopFrames();await assert.rejects(p,/feedback_stale/);await sleep(20);
 assert.equal(received.filter(m=>m.cmd==='software_stop').length,1);
 assert.equal(received.some(m=>['connect','disconnect'].includes(m.cmd)),false);
});
test('one in-flight command and web-only command allowlist are enforced',async t=>{
 const {client}=await setup(t);const p=client.command({cmd:'gripper',position:1},100);p.catch(()=>{});
 await assert.rejects(client.command({cmd:'gripper',position:0}),/command_in_flight/);
 await assert.rejects(client.command({cmd:'connect'}),/command_forbidden/);
 await assert.rejects(p,/command_timeout/);
});
test('bound terminal-only bridge motion waits for post-completion fresh state without dropping SDK',async t=>{
 let stopFrames;const {client,received,stopFrames:stop}=await setup(t,(s,m)=>{
  if(m.cmd==='software_stop'){s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,stopped:true}));return;}
  stopFrames();s.send(JSON.stringify({type:'command_status',status:'accepted',request_id:m.request_id}));
  s.send(JSON.stringify({type:'motion_state',stateName:'MOVING'}));
  setTimeout(()=>s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,reached:true,robot_healthy:true})),180);
  setTimeout(()=>{const state=robot(1000);state.flange_position_m=[0.305,0,0.2];s.send(JSON.stringify(state));},210);
 },{terminalFeedbackOnly:true});stopFrames=stop;
 const result=await client.command({cmd:'move_l',position:[0.305,0,0.2],euler:[0,0,0]},600);
 assert.equal(result.reached,true);assert.equal(client.state().state_sequence,1000);
 assert.deepEqual(received.map(m=>m.cmd),['move_l']);
});
test('alignment waits for actual final IDLE snapshot after its correlated completion',async t=>{
 const {client,stopFrames}=await setup(t,(s,m)=>{
  stopFrames();s.send(JSON.stringify({type:'command_status',status:'accepted',request_id:m.request_id}));
  s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,reached:true,robot_healthy:true}));
  setTimeout(()=>{const state=robot(1000);state.joints_deg=[0,0,-1,1,0,0];s.send(JSON.stringify(state));},30);
 });
 const result=await client.execute({operation:'vision.align.step',primitiveId:'test-align',parameters:{tier:'wrist',startJointsDeg:[0,0,-1,0,0,0],targetJointsDeg:[0,0,-1,1,0,0],timeoutMs:500}});
 assert.equal(result.status,'completed');
});
test('unattributed error after accepted motion stops uncertain execution once',async t=>{
 const {client,received}=await setup(t,(s,m)=>{
  if(m.cmd==='software_stop'){s.send(JSON.stringify({type:'command_status',status:'complete',request_id:m.request_id,stopped:true}));return;}
  s.send(JSON.stringify({type:'command_status',status:'accepted',request_id:m.request_id}));
  s.send(JSON.stringify({type:'error',msg:'joint motion failed'}));
 });
 await assert.rejects(client.command({cmd:'move_l',position:[0.305,0,0.2],euler:[0,0,0]}),/robot_error/);await sleep(20);
 assert.equal(received.filter(m=>m.cmd==='software_stop').length,1);
});
