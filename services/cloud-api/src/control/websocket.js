'use strict';
const {WebSocketServer,WebSocket}=require('ws');
const {randomUUID}=require('node:crypto');
const {authorize}=require('../../../../platform/identity/src/policy');
const {UUID}=require('../../../device-relay/src/protocol');
function createControlWebSocket({sessions,channels,controlService,publicOrigin,maxConnections=16,onTiming=()=>{}}){
  const wss=new WebSocketServer({noServer:true,maxPayload:8192,perMessageDeflate:false}),clients=new Set();
  const revoked=({sessionId})=>{for(const item of clients)if(item.principal.sessionId===sessionId)item.ws.close(1008,'Session revoked');};
  const unavailable=()=>{for(const item of clients)item.ws.close(1013,'Identity unavailable');};
  sessions.events.on('revoked',revoked);sessions.events.on('unavailable',unavailable);
  return {async upgrade(request,socket,head){
    if(new URL(request.url,publicOrigin).pathname!=='/stream/v1/control')return false;
    try{
      if(request.url!=='/stream/v1/control'||request.method!=='GET'||request.headers.origin!==publicOrigin||clients.size>=maxConnections)throw Error();
      const principal=await sessions.resolveSession(request);if(!authorize(principal,'control.request').ok)throw Error();
      if(socket.destroyed)return true;
      wss.handleUpgrade(request,socket,head,ws=>{
        const item={ws,principal};clients.add(item);let connectionId=null,processing=false,lastResponse=performance.now();
        const queue=[],traceId=randomUUID();
        const duration=value=>Math.max(0,Math.min(60000,Math.round(value)));
        const report=value=>{try{onTiming(Object.freeze({traceId,...value}));}catch{/* Diagnostics cannot authorize or reject a control response. */}};
        const send=value=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(value));};
        // Revocation must precede the close handshake: an unresponsive peer can
        // keep TCP open after receiving our close frame.
        const reject=reason=>{queue.length=0;if(connectionId)channels.close(connectionId);ws.close(1008,reason);};
        const timeout=setTimeout(()=>reject('Control bind timeout'),3000);timeout.unref();
        const timer=setInterval(()=>{if(connectionId){if(performance.now()-lastResponse>1500){reject('Control response expired');return;}try{channels.challenge(connectionId);}catch{reject('Control connection revoked');}}},250);timer.unref();
        ws.on('error',()=>{});
        ws.on('close',()=>{queue.length=0;clearTimeout(timeout);clearInterval(timer);clients.delete(item);if(connectionId)channels.close(connectionId);});
        async function handle({raw,receivedAt}){
          const processingAt=performance.now();let stage='browser_response',authMs=0;
          const metric=(outcome,code)=>report({stage,outcome,elapsedMs:duration(performance.now()-receivedAt),queueMs:duration(processingAt-receivedAt),authMs,...(code?{code}:{})});
          try{
            const message=JSON.parse(raw.toString('utf8'));
            if(message?.type==='bind')stage='control_bind';
            const authStarted=performance.now();let fresh;
            try{fresh=await sessions.resolveSession(request);}finally{authMs=duration(performance.now()-authStarted);}
            if(ws.readyState!==WebSocket.OPEN){metric('rejected','CONTROL_CLOSED');return;}
            if(!fresh||fresh.sessionId!==principal.sessionId||!authorize(fresh,'control.command').ok)throw Error();
            if(!connectionId){
              if(!message||message.type!=='bind'||Object.keys(message).length!==3||!UUID.test(message.clientInstanceId)||!sessions.verifyCsrf({headers:{'x-csrf-token':message.csrfToken}},fresh))throw Error();
              const bound=channels.open(fresh,{clientInstanceId:message.clientInstanceId,send});connectionId=bound.connectionId;clearTimeout(timeout);
              send({type:'bound',connectionId,clientInstanceId:message.clientInstanceId});channels.challenge(connectionId);
            }else if(message.type==='response'&&Object.keys(message).length===4&&message.connectionId===connectionId){
              channels.respond(fresh,message);lastResponse=performance.now();send({type:'fresh',connectionId,sequence:message.sequence});
            }else throw Error();
            metric('accepted');
          }catch(error){metric('rejected',['STALE_CHALLENGE','FORBIDDEN','BROWSER_STALE'].includes(error?.code)?error.code:'AUTHORIZATION_REJECTED');reject('Control authorization rejected');}
        }
        async function drain(){
          if(processing)return;processing=true;
          try{while(queue.length&&ws.readyState===WebSocket.OPEN)await handle(queue.shift());}
          finally{processing=false;}
        }
        ws.on('message',(raw,isBinary)=>{
          // TCP may deliver two legitimate challenge responses together. An
          // asynchronous identity lookup must not turn that burst into a
          // protocol violation. Keep at most one waiting response, and still
          // verify its original challenge expiry after authorization resolves.
          if(isBinary||queue.length+(processing?1:0)>=2){reject('Invalid control message');return;}
          queue.push({raw,receivedAt:performance.now()});void drain();
        });
      });
    }catch{if(!socket.destroyed)socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');}
    return true;
  },async close(){sessions.events.off('revoked',revoked);sessions.events.off('unavailable',unavailable);for(const {ws}of clients)ws.terminate();await new Promise(resolve=>wss.close(resolve));}};
}
module.exports={createControlWebSocket};
