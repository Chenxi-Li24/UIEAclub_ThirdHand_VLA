'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { RobotController } = require('../../../services/robot/src/robot-controller');
const { createRobotService } = require('../../../services/robot/src/server');
const { WebSocket } = require('ws');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

test('only authenticated Meituan route commands reach the bridge at 20 percent', () => {
  const robot = new RobotController({ speedScale: 0.05 });
  const sent = [], replies = [];
  robot._motionReadinessError = () => null;
  robot.bridge.send = command => { sent.push(command); return true; };
  const commands = [
    {cmd:'servo', joints:[10,90,-90,30,0,0]},
    {cmd:'preset', name:'zero'},
    {cmd:'move_l', position:[0.4,0,0.3], euler:[0,0,0]},
  ];
  for (const command of commands) {
    robot.handleCommand({...command, speed_profile:'meituan_20'}, r=>replies.push(r));
    assert.equal(sent.length, 0, 'ordinary client cannot forge the profile');
    assert.equal(replies.at(-1).code, 'meituan_speed_unauthorized');
    robot.handleCommand({...command, speed_profile:'meituan_20'}, r=>replies.push(r), 'test', true);
    assert.equal(sent.pop().speed_percent, 0.20);
    robot.handleCommand(command, r=>replies.push(r), 'test', true);
    assert.equal(sent.pop().speed_percent, 0.05, 'private connection alone does not accelerate manual commands');
    robot.handleCommand({...command,speed_percent:0.20}, r=>replies.push(r));
    assert.equal(sent.pop().speed_percent, 0.05);
  }
});

test('Meituan WebSocket requires its own token and binds authorization on the server', {timeout:5000}, async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'meituan-auth-'));
  const service=createRobotService({host:'127.0.0.1',port:0,readyFile:path.join(dir,'ready'),meituanToken:'b'.repeat(64)});
  service.controller.start=async()=>{};
  service.controller.shutdown=async()=>{};
  service.controller._motionReadinessError=()=>null;
  const commands=[];
  let delivered;
  const delivery=new Promise(resolve=>{delivered=resolve;});
  service.controller.bridge.send=c=>{commands.push(c);delivered();return true;};
  t.after(async()=>{await service.close();fs.rmSync(dir,{recursive:true,force:true});});
  const address=await service.start();
  const open=(route,token)=>new Promise((resolve,reject)=>{
    const socket=new WebSocket(`ws://127.0.0.1:${address.port}${route}`,{headers:token?{'x-thirdhand-meituan-token':token}:{}});
    socket.once('open',()=>resolve(socket));socket.once('error',reject);
  });
  await assert.rejects(open('/meituan'),/401/);
  await assert.rejects(open('/meituan','a'.repeat(64)),/401/);
  const privateSocket=await open('/meituan','b'.repeat(64));
  t.after(()=>privateSocket.terminate());
  privateSocket.send(JSON.stringify({cmd:'servo',joints:[10,90,-90,30,0,0],speed_profile:'meituan_20'}));
  await delivery;
  assert.equal(commands.pop()?.speed_percent,0.20);
  const ordinary=await open('/ws','b'.repeat(64));
  t.after(()=>ordinary.terminate());
  const rejected=new Promise(resolve=>ordinary.on('message',data=>{
    const message=JSON.parse(data);if(message.type==='error')resolve(message);
  }));
  ordinary.send(JSON.stringify({cmd:'servo',joints:[10,90,-90,30,0,0],speed_profile:'meituan_20'}));
  assert.equal((await rejected).code,'meituan_speed_unauthorized');
  assert.equal(commands.length,0);
});
