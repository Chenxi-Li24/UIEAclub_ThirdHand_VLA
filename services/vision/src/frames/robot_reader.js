'use strict';
const {WebSocket}=require('ws');
const {loadPolicy,normalizeRobotState}=require('./robot_frame_normalization');
function startReader(url,onState,{policy=null}={}){
  let closed=false,socket=null,timer=null;
  function connect(){
    if(closed)return;
    socket=new WebSocket(url,{handshakeTimeout:5000});
    socket.on('message',raw=>{
      try {
        const m=JSON.parse(raw);if(m?.type!=='robot_state')return;
        try{onState(normalizeRobotState(m,policy));}
        catch(error){onState({type:'robot_state',connected:false,healthy:false,frame_error:error.message});}
      } catch {}
    });
    socket.on('error',()=>{});
    socket.on('close',()=>{
      if(closed)return;
      onState({type:'robot_state',connected:false});
      timer=setTimeout(connect,1000);
    });
  }
  connect();
  return {close(){closed=true;clearTimeout(timer);socket?.terminate();}};
}
if(require.main===module){
  const policy=loadPolicy(process.env.THIRDHAND_ROBOT_FRAME_POLICY);
  const reader=startReader(process.argv[2]||'ws://127.0.0.1:3000/ws',m=>process.stdout.write(JSON.stringify(m)+'\n'),{policy});
  for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>reader.close());
}
module.exports={startReader};
