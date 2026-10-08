'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const http=require('node:http'),{EventEmitter,once}=require('node:events');
const {WebSocket}=require('ws');

async function setup(t, ready=true) {
  const entry=path.join(__dirname,'../../../services/vision/src/meituan-recognition.js');
  assert.ok(fs.existsSync(entry),'isolated 1035 recognition controller missing');
  const {attachRecognition}=require(entry);
  const camera=new EventEmitter();
  camera.commands=[]; camera.meituanReady=ready;
  camera.status=()=>({camera:{status:'ready'},selection:{stableId:1,requestId:'bottle'}});
  camera.send=msg=>{camera.commands.push(msg);return true;};
  const logs=fs.mkdtempSync(path.join(os.tmpdir(),'battery-log-'));
  let api;
  const server=http.createServer((req,res)=>{
    if(!api.handleHttp(req,res,new URL(req.url,'http://localhost').pathname)){res.writeHead(404);res.end();}
  });
  api=attachRecognition({server,camera,host:'127.0.0.1',logDir:logs});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port;
  const socket=new WebSocket('ws://127.0.0.1:'+port+'/ws',{origin:'http://127.0.0.1:1034'});
  const messages=[];
  socket.on('message',data=>messages.push(JSON.parse(data)));
  await once(socket,'open');
  async function wait(type) {
    const deadline=Date.now()+2000;
    while(Date.now()<deadline) {
      const i=messages.findIndex(m=>m.type===type);
      if(i>=0)return messages.splice(i,1)[0];
      await new Promise(r=>setTimeout(r,5));
    }
    throw new Error('missing '+type);
  }
  t.after(async()=>{socket.terminate();await api.close();await new Promise(r=>server.close(r));fs.rmSync(logs,{recursive:true,force:true});});
  return {api,camera,socket,wait,port,logs};
}

test('1035 start submits one request and continuous results stay out of bottle selection',async t=>{
  const {api,camera,socket,wait}=await setup(t);
  socket.send(JSON.stringify({type:'start',parameters:{prompt:'battery .',boxThreshold:.3,textThreshold:.25}}));
  await wait('battery.status');
  for(let i=0;i<50 && !camera.commands.length;i++)await new Promise(r=>setTimeout(r,5));
  const cmd=camera.commands[0];
  assert.equal(cmd.type,'meituan_detect');
  assert.equal(cmd.parameters.prompt,'battery .');
  camera.emit('meituan',{type:'meituan_result',sessionId:cmd.sessionId,requestId:cmd.requestId,frameId:9,
    detections:[{id:1,color:'red',score:.9}],jpegBase64:Buffer.from([255,216,255,217]).toString('base64')});
  const result=await wait('battery.result');
  assert.equal(result.frameId,9);
  assert.equal(result.detections[0].color,'red');
  assert.equal(camera.commands.filter(c=>c.type==='meituan_detect').length,2);
  assert.deepEqual(camera.status().selection,{stableId:1,requestId:'bottle'});
  assert.equal(api.status().state,'running');
});

test('stop drops late results; malformed parameters never change bottle commands',async t=>{
  const {api,camera,socket,wait}=await setup(t);
  socket.send(JSON.stringify({type:'start',parameters:{boxThreshold:0}}));
  assert.equal((await wait('battery.error')).code,'invalid_parameters');
  assert.equal(camera.commands.length,0);
  socket.send(JSON.stringify({type:'start',parameters:{}}));
  for(let i=0;i<50 && !camera.commands.length;i++)await new Promise(r=>setTimeout(r,5));
  const cmd=camera.commands[0];
  socket.send(JSON.stringify({type:'stop'}));
  for(let i=0;i<50 && api.status().state==='running';i++)await new Promise(r=>setTimeout(r,5));
  camera.emit('meituan',{...cmd,type:'meituan_result',frameId:10,jpegBase64:'abcd',detections:[]});
  assert.equal(api.status().state,'stopped');
  assert.equal(camera.commands.filter(c=>c.type==='meituan_detect').length,1);
  assert.ok(camera.commands.some(c=>c.type==='meituan_cancel'));
});

test('inference error stops battery and retains full trace in disk logs',async t=>{
  const {api,camera,socket,wait,logs}=await setup(t);
  socket.send(JSON.stringify({type:'start',parameters:{}}));
  for(let i=0;i<50 && !camera.commands.length;i++)await new Promise(r=>setTimeout(r,5));
  const cmd=camera.commands[0];
  camera.emit('meituan',{type:'meituan_error',sessionId:cmd.sessionId,requestId:cmd.requestId,frameId:4,
    error:{message:'OOM',stack:'Traceback\nCUDA out of memory'}});
  const error=await wait('battery.error');
  assert.match(error.error.stack,/CUDA out of memory/);
  assert.equal(api.status().state,'error');
  assert.equal(camera.commands.filter(c=>c.type==='meituan_detect').length,1);
  assert.match(fs.readFileSync(path.join(logs,'meituan-battery.jsonl'),'utf8'),/CUDA out of memory/);
});

test('control disconnect stops requests independently of video subscriptions',async t=>{
  const {api,camera,socket}=await setup(t);
  socket.send(JSON.stringify({type:'start',parameters:{}}));
  for(let i=0;i<50 && !camera.commands.length;i++)await new Promise(r=>setTimeout(r,5));
  socket.close();
  for(let i=0;i<50 && api.status().state==='running';i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(api.status().state,'stopped');
  assert.ok(camera.commands.some(c=>c.type==='meituan_cancel'));
});

test('model-ready event enables an already-open battery panel without reconnecting',async t=>{
  const {camera,wait}=await setup(t,false);
  assert.equal((await wait('battery.status')).available,false);
  camera.meituanReady=true;
  camera.emit('meituan',{type:'meituan_ready'});
  assert.equal((await wait('battery.status')).available,true);
});

test('JSON null and primitive commands are rejected without crashing the shared owner',async t=>{
  const {camera,socket,wait}=await setup(t);
  await wait('battery.status');
  for(const value of [null,7,'start',[]]){
    socket.send(JSON.stringify(value));
    assert.equal((await wait('battery.error')).code,'invalid_message');
  }
  assert.equal(camera.commands.length,0);
  socket.send(JSON.stringify({type:'start',parameters:{}}));
  assert.equal((await wait('battery.status')).state,'running');
  assert.equal(camera.commands[0].type,'meituan_detect');
});

for(const trigger of ['stop','disconnect'])test('another panel can start after owner '+trigger,async t=>{
  const {api,camera,socket,wait,port}=await setup(t);
  await wait('battery.status');
  socket.send(JSON.stringify({type:'start',parameters:{}}));
  assert.equal((await wait('battery.status')).state,'running');
  const observer=new WebSocket('ws://127.0.0.1:'+port+'/ws',{origin:'http://127.0.0.1:1034'});
  t.after(()=>observer.terminate());
  const states=[];
  observer.on('message',data=>{const value=JSON.parse(data);if(value.type==='battery.status')states.push(value.state);});
  await once(observer,'open');
  async function observed(state){
    const deadline=Date.now()+1000;
    while(Date.now()<deadline){
      const i=states.indexOf(state);
      if(i>=0){states.splice(i,1);return;}
      await new Promise(r=>setTimeout(r,5));
    }
    assert.fail('observer did not receive '+state);
  }
  await observed('running');
  if(trigger==='stop')socket.send(JSON.stringify({type:'stop'}));else socket.close();
  await observed('stopped');
  observer.send(JSON.stringify({type:'start',parameters:{}}));
  await observed('running');
  assert.equal(api.status().state,'running');
  assert.equal(camera.commands.filter(c=>c.type==='meituan_detect').length,2);
});
