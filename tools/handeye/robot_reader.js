'use strict';
const {WebSocket}=require('ws');
function startReader(url,onState){
  let closed=false,socket=null,timer=null;
  function connect(){
    if(closed)return;
    socket=new WebSocket(url,{handshakeTimeout:5000});
    socket.on('message',raw=>{
      try {const m=JSON.parse(raw);if(m?.type==='robot_state')onState(m);} catch {}
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
  const reader=startReader(process.argv[2]||'ws://192.168.58.68:9983/ws',m=>process.stdout.write(JSON.stringify(m)+'\n'));
  for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>reader.close());
}
module.exports={startReader};
