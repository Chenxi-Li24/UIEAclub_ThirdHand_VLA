'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {WebSocketServer}=require('ws');
const {startReader}=require('./robot_reader');
test('read-only subscriber forwards state and sends no command',async()=>{
  const server=new WebSocketServer({port:0});
  await new Promise(resolve=>server.once('listening',resolve));
  let commands=0;
  const state={type:'robot_state',state_sequence:1};
  server.on('connection',socket=>{
    socket.on('message',()=>commands++);
    socket.send(JSON.stringify({type:'config'}));
    socket.send(JSON.stringify(state));
  });
  const received=[];
  const reader=startReader(`ws://127.0.0.1:${server.address().port}`,x=>received.push(x));
  try {
    await new Promise(resolve=>setTimeout(resolve,100));
    assert.deepEqual(received,[state]);
    assert.equal(commands,0);
  } finally {reader.close();for(const s of server.clients)s.terminate();await new Promise(r=>server.close(r));}
});
