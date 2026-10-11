'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{WebSocketServer}=require('ws');
const {WebRobotClient}=require('../../../apps/web/src/grasp/robot-client');
test('gateway factory can defer its self-connection until public listener is ready',async t=>{
 const wss=new WebSocketServer({port:0});await new Promise(r=>wss.once('listening',r));let connections=0;
 wss.on('connection',s=>{connections++;s.send(JSON.stringify({type:'robot_state',connected:true,healthy:true,stateName:'IDLE',moving:false,
  state_sequence:1,joints_deg:[0,0,-1,0,0,0],flange_position_m:[0.3,0,0.2],flange_euler_rad:[0,0,0],gripper_width_m:0.03}));});
 const c=new WebRobotClient({url:`ws://127.0.0.1:${wss.address().port}/ws`,deferConnect:true});
 t.after(async()=>{c.close();for(const s of wss.clients)s.terminate();await new Promise(r=>wss.close(r));});
 await new Promise(r=>setTimeout(r,30));assert.equal(connections,0);
 await c.ready();assert.equal(connections,1);
});
