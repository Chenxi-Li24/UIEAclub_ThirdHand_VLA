'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { once } = require('node:events');
const { WebSocket, WebSocketServer } = require('ws');
const { createVisionService } = require('../../../services/vision/src/server');

test('configured vision service automatically relays canonical feedback without robot commands',async t=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'vision-auto-relay-'));
 const robot=new WebSocketServer({host:'127.0.0.1',port:0});await once(robot,'listening');
 const received=[],commands=[];
 const service=createVisionService({env:{THIRDHAND_ROBOT_FRAME_POLICY:path.resolve(__dirname,'../../../configs/vision/sdk-tool-frame-policy.json'),ROBOT_WS_URL:`ws://127.0.0.1:${robot.address().port}`},
  host:'127.0.0.1',port:0,readyFile:path.join(temp,'ready'),
  camera:{start(){},async close(){},status:()=>({camera:{status:'ready'}}),send:m=>{received.push(m);return true;}}});
 t.after(async()=>{await service.close();for(const s of robot.clients)s.terminate();await new Promise(r=>robot.close(r));fs.rmSync(temp,{recursive:true,force:true});});
 const connected=once(robot,'connection');await service.start();
 const connection=await Promise.race([connected,new Promise(r=>setTimeout(()=>r(null),750))]);assert.ok(connection,'automatic feedback relay missing');
 const [socket]=connection;socket.on('message',m=>commands.push(m));
 socket.send(JSON.stringify({type:'robot_state',connected:true,healthy:true,moving:false,pose_frame:'robot_flange',state_sequence:1,
  producer_monotonic_ns:Number(process.hrtime.bigint()),flange_position_m:[.37334,0,.2],flange_euler_rad:[0,0,0],joints_deg:[0,0,-1,0,0,0],velocities_deg_s:[0,0,0,0,0,0]}));
 for(let n=0;n<50&&!received.length;n++)await new Promise(r=>setTimeout(r,10));
 assert.deepEqual(received[0]?.flange_position_m,[.2,0,.2]);assert.equal(commands.length,0);
});

test('projection telemetry reaches only the existing ready camera', async t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'vision-state-route-'));
  const sent = [];
  let ready = true;
  const camera = {
    start() {}, async close() {},
    status: () => ({ camera: { status: ready ? 'ready' : 'starting' } }),
    send: message => { sent.push(message); return true; },
  };
  const service = createVisionService({ camera, env: {}, host: '127.0.0.1', port: 0,
    readyFile: path.join(temp, 'ready.json') });
  const address = await service.start();
  const socket = new WebSocket(`ws://127.0.0.1:${address.port}/ws`);
  t.after(async () => {
    socket.terminate();
    await service.close();
    fs.rmSync(temp, { recursive: true, force: true });
  });
  await once(socket, 'open');
  const state = {type:'arm_state', pose_frame:'robot_flange', connected:true,
    healthy:true, stationary:true, flange_position_m:[0.1,0,0.2],
    flange_euler_rad:[0,0,0], joints_deg:[0,0,0,0,0,0], observed_monotonic_ns:123};
  socket.send(JSON.stringify(state));
  for (let i=0; i<50 && !sent.length; i++) await new Promise(resolve=>setTimeout(resolve,5));
  assert.deepEqual(sent, [state]);
  ready = false;
  const rejected = once(socket, 'message');
  socket.send(JSON.stringify(state));
  assert.equal(JSON.parse((await rejected)[0]).type, 'command_rejected');
  assert.equal(sent.length, 1);
});
