'use strict';
const fs=require('node:fs'),path=require('node:path');
const {randomUUID}=require('node:crypto');
const {WebSocket,WebSocketServer}=require('ws');
const {LatestMjpegBroadcaster}=require('./camera-process');

function attachRecognition({server,camera,host,logDir=path.resolve(__dirname,'../../../runtime/logs'),requestTimeoutMs=30000}) {
  const config=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../../configs/meituan/vision.json'),'utf8'));
  const defaults=Object.fromEntries(['prompt','boxThreshold','textThreshold'].map(key=>[key,config[key]]));
  const video=new LatestMjpegBroadcaster();
  const wss=new WebSocketServer({noServer:true,maxPayload:8192});
  const logs=[];
  let owner=null,session=null,params={...defaults},pending=null,timer=null,state='stopped',closed=false;
  function send(socket,message) {if(socket?.readyState===WebSocket.OPEN)socket.send(JSON.stringify(message));}
  function status() {return {state,available:camera.meituanReady===true,defaults};}
  function broadcastStatus() {for(const client of wss.clients)send(client,{type:'battery.status',...status(),parameters:params});}
  function log(entry) {
    const value={timestamp:Date.now(),...entry};
    logs.push(value);
    if(logs.length>200)logs.shift();
    try {
      fs.mkdirSync(logDir,{recursive:true});
      fs.appendFileSync(path.join(logDir,'meituan-battery.jsonl'),JSON.stringify(value)+'\n',{mode:0o600});
    } catch(error) {
      value.logWriteError=error.message;
    }
    for(const client of wss.clients)send(client,{type:'battery.log',entry:value});
  }
  function stop(next='stopped') {
    clearTimeout(timer); timer=null; pending=null;
    if(session)camera.send({type:'meituan_cancel',sessionId:session});
    session=null;state=next;video.reset();broadcastStatus();
  }
  function fail(code,error) {
    const detail=typeof error==='string'?{message:error}:error;
    log({level:'error',code,error:detail,parameters:params,sessionId:session,requestId:pending});
    stop('error');
    send(owner,{type:'battery.error',code,error:detail});
  }
  function validate(value) {
    if(value===undefined)value={};
    if(!value || typeof value!=='object' || Array.isArray(value) ||
       Object.keys(value).some(key=>!Object.hasOwn(defaults,key)))throw new Error('invalid parameter fields');
    const next={...defaults,...value};
    if(typeof next.prompt!=='string' || !next.prompt.trim() || next.prompt.trim().length>512)throw new Error('prompt must contain 1..512 characters');
    next.prompt=next.prompt.trim();
    for(const key of ['boxThreshold','textThreshold'])
      if(typeof next[key]!=='number' || !Number.isFinite(next[key]) || next[key]<=0 || next[key]>1)throw new Error(key+' must be within (0,1]');
    return next;
  }
  function request() {
    if(closed || state!=='running' || pending)return;
    if(camera.meituanReady!==true || camera.status().camera.status!=='ready')return fail('shared_hook_unavailable','Shared battery hook/camera is not ready');
    pending=randomUUID();
    const accepted=camera.send({type:'meituan_detect',sessionId:session,requestId:pending,parameters:params});
    if(!accepted)return fail('camera_command_failed','Unable to submit battery request');
    timer=setTimeout(()=>fail('inference_timeout','Battery inference timed out'),requestTimeoutMs);
    timer.unref();
  }
  function onEvent(message) {
    if(message.type==='meituan_log') {log(message);return;}
    if(message.type==='meituan_ready') {
      broadcastStatus();
      return;
    }
    if(message.sessionId!==session || message.requestId!==pending || state!=='running')return;
    if(message.type==='meituan_error')return fail('inference_failed',message.error);
    if(message.type!=='meituan_result')return;
    clearTimeout(timer);timer=null;pending=null;
    if(typeof message.jpegBase64!=='string' || message.jpegBase64.length>4*1024*1024 ||
       !Array.isArray(message.detections))return fail('invalid_result','Invalid battery result');
    const jpeg=Buffer.from(message.jpegBase64,'base64');
    if(jpeg.length<4 || jpeg[0]!==255 || jpeg[1]!==216)return fail('invalid_result','Invalid annotated JPEG');
    video.push(Buffer.concat([
      Buffer.from('--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+jpeg.length+
        '\r\nX-Frame-Id: '+Number(message.frameId)+'\r\n\r\n'),jpeg,Buffer.from('\r\n')]));
    const {jpegBase64,...result}=message;
    send(owner,{...result,type:'battery.result'});
    request();
  }
  camera.on('meituan',onEvent);
  function onUpgrade(request,socket,head) {
    if(new URL(request.url,'http://localhost').pathname!=='/ws'){socket.destroy();return;}
    try {
      const origin=new URL(request.headers.origin);
      if(!['http:','https:'].includes(origin.protocol) || origin.hostname!==host || origin.port!=='1034')throw new Error('origin');
    } catch {socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');socket.destroy();return;}
    wss.handleUpgrade(request,socket,head,ws=>wss.emit('connection',ws));
  }
  server.on('upgrade',onUpgrade);
  wss.on('connection',socket=>{
    socket.alive=true;
    socket.on('pong',()=>{socket.alive=true;});
    send(socket,{type:'battery.status',...status(),logs});
    socket.on('message',data=>{
      let message;
      try {
        message=JSON.parse(data);
        if(!message || typeof message!=='object' || Array.isArray(message))throw new Error('invalid shape');
      } catch {send(socket,{type:'battery.error',code:'invalid_message',error:{message:'Invalid battery message'}});return;}
      if(message.type==='stop') {
        if(owner===socket)stop();
        return;
      }
      if(message.type!=='start' && message.type!=='configure'){
        send(socket,{type:'battery.error',code:'invalid_message',error:{message:'Unsupported battery command'}});return;
      }
      if(owner && owner!==socket && state==='running'){
        send(socket,{type:'battery.error',code:'battery_session_busy',error:{message:'Another Meituan session is active'}});return;
      }
      let next;
      try {next=validate(message.parameters);}
      catch(error){send(socket,{type:'battery.error',code:'invalid_parameters',error:{message:error.message}});return;}
      if(message.type==='configure' && owner!==socket){
        send(socket,{type:'battery.error',code:'session_not_running',error:{message:'Start recognition first'}});return;
      }
      owner=socket;params=next;
      if(state!=='running') {session=randomUUID();state='running';}
      broadcastStatus();
      request();
    });
    socket.on('close',()=>{if(owner===socket){stop();owner=null;}});
    socket.on('error',()=>{if(owner===socket){stop();owner=null;}});
  });
  const heartbeat=setInterval(()=>{
    for(const client of wss.clients){
      if(!client.alive){client.terminate();continue;}
      client.alive=false;client.ping();
    }
  },10000);
  heartbeat.unref();
  return {
    status,
    handleHttp(request,response,pathname) {
      if(request.method!=='GET')return false;
      if(pathname==='/api/meituan/vision/logs'){
        response.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
        response.end(JSON.stringify({logs}));return true;
      }
      if(pathname!=='/camera/xvisio/vision')return false;
      if(state!=='running'){
        response.writeHead(409,{'content-type':'application/json','cache-control':'no-store'});
        response.end(JSON.stringify({code:'battery_recognition_stopped'}));return true;
      }
      response.writeHead(200,{'content-type':'multipart/x-mixed-replace; boundary=frame','cache-control':'no-store'});
      video.subscribe(response);
      response.on('close',()=>video.unsubscribe(response));
      return true;
    },
    async close() {
      closed=true;stop();clearInterval(heartbeat);
      server.off('upgrade',onUpgrade);camera.off('meituan',onEvent);
      video.close();
      for(const client of wss.clients)client.terminate();
      await new Promise(resolve=>wss.close(resolve));
    }
  };
}
module.exports={attachRecognition};
