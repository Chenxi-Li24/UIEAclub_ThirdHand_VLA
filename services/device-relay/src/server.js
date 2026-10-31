'use strict';
const https=require('node:https');
const http=require('node:http');
const {EventEmitter}=require('node:events');
const {X509Certificate,randomUUID,randomBytes,verify}=require('node:crypto');
const {WebSocketServer,WebSocket}=require('ws');
const {parseMessage,validateHello,decodeBase64url,validateEnvelope,object,UUID}=require('./protocol');

function mediaNegotiation(headers){
  const version=headers['x-thirdhand-media-grant'],digest=headers['x-thirdhand-media-credentials'];
  if(version===undefined){if(digest!==undefined)throw Error('INVALID_MEDIA_NEGOTIATION');return null;}
  if(typeof version!=='string'||!/^[A-Za-z0-9_-]{1,32}$/.test(version))throw Error('INVALID_MEDIA_NEGOTIATION');
  if(version!=='compact-v1'){if(digest!==undefined)throw Error('INVALID_MEDIA_NEGOTIATION');return null;}
  if(digest===undefined)return {format:'compact-v1',credentialDigest:null};
  if(typeof digest!=='string'||digest.length!==43||decodeBase64url(digest,43).length!==32)throw Error('INVALID_MEDIA_NEGOTIATION');
  return {format:'compact-v1',credentialDigest:digest};
}

function createDeviceRelay({store,ingestBatch,mediaPublisher,tls=null,trustedUnixProxy=false,clock={now:()=>new Date()},handshakeTimeoutMs=5000,heartbeatTimeoutMs=15000,maxDevices=128}){
  if(!store?.resolveCertificate||(!tls&&!trustedUnixProxy)||tls&&trustedUnixProxy)throw Error('Choose mTLS or a private Unix proxy');
  const active=new Map(),sockets=new Set(),networkSockets=new Set(),events=new EventEmitter();
  const now=()=>clock.now().getTime();
  async function stillRegistered(registered){
    if(now()>=registered.validUntil)return false;
    const row=await store.resolveCertificate(registered.fingerprint);
    return !!row&&row.id===registered.id&&row.certificateId===registered.certificateId&&(!registered.remoteControlEnabled||row.remoteControlEnabled===true)&&row.readOnly===registered.readOnly&&row.publicKey.export({format:'der',type:'spki'}).equals(registered.publicKey.export({format:'der',type:'spki'}));
  }
  async function identity(request){
    if(request.headers.origin||request.headers.cookie)throw Error('DEVICE_ONLY');
    let cert;
    if(tls){
      if(!request.socket.authorized)throw Error('MTLS_REQUIRED');
      // Forwarded certificate headers are never used on the direct TLS listener.
      if(Object.keys(request.headers).some(key=>key.startsWith('x-ssl-client-')))throw Error('FORGED_HEADERS');
      cert=new X509Certificate(request.socket.getPeerCertificate().raw);
    }else{
      if(request.socket.remoteAddress||request.headers['x-ssl-client-verify']!=='SUCCESS')throw Error('UNIX_PROXY_REQUIRED');
      const encoded=request.headers['x-ssl-client-cert'];
      if(typeof encoded!=='string'||encoded.length>12000)throw Error('INVALID_CERTIFICATE');
      cert=new X509Certificate(decodeURIComponent(encoded));
    }
    if(now()<cert.validFromDate.getTime()||now()>=cert.validToDate.getTime()||cert.publicKey.asymmetricKeyType!=='ed25519')throw Error('INVALID_CERTIFICATE');
    const fingerprint=cert.fingerprint256.replaceAll(':','').toLowerCase();
    const registered=await store.resolveCertificate(fingerprint);
    if(!registered||registered.fingerprint!==fingerprint||!registered.publicKey.export({format:'der',type:'spki'}).equals(cert.publicKey.export({format:'der',type:'spki'})))throw Error('UNKNOWN_CERTIFICATE');
    return {...registered,fingerprint,validUntil:cert.validToDate.getTime()};
  }
  const handler=async(request,response)=>{
    response.setHeader('Cache-Control','no-store');response.setHeader('Content-Type','application/json');
    let uploadVerified=false;
    try{
      if(request.url==='/edge/v1/media-grant'&&request.method==='POST'&&mediaPublisher){
        const registered=await identity(request);
        const negotiation=mediaNegotiation(request.headers);
        if(!/^application\/json(?:\s*;.*)?$/i.test(request.headers['content-type']||''))throw Error('INVALID_MEDIA_REQUEST');
        const chunks=[];let size=0;for await(const chunk of request){size+=chunk.length;if(size>24000)throw Error('MEDIA_REQUEST_TOO_LARGE');chunks.push(chunk);}
        const envelope=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(!object(envelope,['payloadBase64url','signatureBase64url'])||Object.keys(envelope).length!==2)throw Error('INVALID_MEDIA_REQUEST');
        const bytes=decodeBase64url(envelope.payloadBase64url);if(!verify(null,bytes,registered.publicKey,decodeBase64url(envelope.signatureBase64url,86)))throw Error('INVALID_MEDIA_SIGNATURE');
        const body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes)),entry=active.get(registered.id);
        if(!object(body,['schema','purpose','context','publisherId','sequence','frame','issuedAt','expiresAt'])||Object.keys(body).length!==8||body.schema!==1||body.purpose!=='media_report'||!object(body.context,['deviceId','bootId','executorEpoch','connectionId','certificateId'])||Object.keys(body.context).length!==5||!entry||entry.ws.readyState!==WebSocket.OPEN||body.context.certificateId!==registered.certificateId||!['deviceId','bootId','executorEpoch','connectionId','certificateId'].every(key=>body.context[key]===entry.context[key])||!Number.isSafeInteger(body.issuedAt)||!Number.isSafeInteger(body.expiresAt)||body.issuedAt>now()+500||body.expiresAt<=now()||body.expiresAt<=body.issuedAt||body.expiresAt-body.issuedAt>1000)throw Error('INVALID_MEDIA_CONTEXT');
        uploadVerified=true;
        const result=await mediaPublisher(entry.context,{publisherId:body.publisherId,sequence:body.sequence,frame:body.frame},negotiation);validateEnvelope(result);response.end(JSON.stringify({envelope:result}));return;
      }
      if(request.url==='/edge/v1/telemetry-batches'&&request.method==='POST'&&ingestBatch){
        const registered=await identity(request);
        if(!/^application\/json(?:\s*;.*)?$/i.test(request.headers['content-type']||''))throw Error('INVALID_UPLOAD');
        const chunks=[];let length=0;for await(const chunk of request){length+=chunk.length;if(length>360000)throw Error('UPLOAD_TOO_LARGE');chunks.push(chunk);}
        const value=JSON.parse(Buffer.concat(chunks).toString('utf8'));
        if(!object(value,['batchId','digest','payloadBase64url','signatureBase64url'])||Object.keys(value).length!==4)throw Error('INVALID_UPLOAD');
        const bytes=decodeBase64url(value.payloadBase64url,349526);if(bytes.length>262144||!verify(null,bytes,registered.publicKey,decodeBase64url(value.signatureBase64url,86)))throw Error('INVALID_UPLOAD_SIGNATURE');
        const body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));if(body.deviceId!==registered.id||!UUID.test(body.bootId))throw Error('INVALID_UPLOAD_DEVICE');
        uploadVerified=true;
        const envelope={batchId:value.batchId,digest:value.digest,payloadBase64url:value.payloadBase64url};
        const result=await ingestBatch({deviceId:registered.id,certificateId:registered.certificateId,bootId:body.bootId},envelope);
        if(result?.persisted!==true||result.batchId!==value.batchId||result.digest!==value.digest)throw Error('UNCOMMITTED_UPLOAD');
        response.end(JSON.stringify(result));return;
      }
      if(request.url!=='/edge/v1/healthz'||request.method!=='GET'){response.writeHead(404);response.end('{}');return;}
      await identity(request);response.end(JSON.stringify({service:'thirdhand-device-relay',protocol:1,controlAuthorized:false}));
    }catch(error){const errors={BATCH_CONFLICT:409,BATCH_SCHEMA:400,BATCH_TOO_LARGE:413,BATCH_DIGEST_MISMATCH:400,BATCH_SEQUENCE_MISMATCH:400,BATCH_ASSOCIATION_MISMATCH:409};const status=errors[error.code]||(uploadVerified?503:403);response.writeHead(status);response.end(JSON.stringify({error:errors[error.code]?error.code:uploadVerified?'DEVICE_UPLOAD_UNAVAILABLE':'DEVICE_UPLOAD_OR_AUTH_FAILED'}));}
  };
  const server=tls?https.createServer({...tls,minVersion:'TLSv1.2',requestCert:true,rejectUnauthorized:true},handler):http.createServer(handler);
  server.on('connection',socket=>{networkSockets.add(socket);socket.once('close',()=>networkSockets.delete(socket));});
  server.maxConnections=256;server.headersTimeout=10000;server.requestTimeout=15000;
  const wss=new WebSocketServer({noServer:true,maxPayload:16384,perMessageDeflate:false});
  server.on('upgrade',async(request,socket,head)=>{
    try{
      if(request.url!=='/edge/v1/connect'||sockets.size>=maxDevices*2)throw Error('INVALID_ENDPOINT');
      const registered=await identity(request);
      if(socket.destroyed)return;
      wss.handleUpgrade(request,socket,head,ws=>open(ws,registered));
    }catch{if(!socket.destroyed)socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');}
  });
  function open(ws,registered){
    sockets.add(ws);let state='hello',context=null,challengeBytes=null,challengeExpiry=0,lastSeen=now(),busy=false,entry=null;
    const pendingRequests=new Map();
    const timer=setTimeout(()=>ws.close(1008,'Authentication timeout'),handshakeTimeoutMs);timer.unref();
    const send=value=>ws.send(JSON.stringify(value));
    ws.on('error',()=>{});
    ws.on('close',()=>{clearTimeout(timer);sockets.delete(ws);for(const pending of pendingRequests.values()){clearTimeout(pending.timer);pending.reject(Error('DEVICE_DISCONNECTED'));}pendingRequests.clear();if(context){if(active.get(context.deviceId)?.context.connectionId===context.connectionId)active.delete(context.deviceId);events.emit('disconnected',context);}});
    ws.on('message',async(raw,isBinary)=>{
      let message;
      try{message=parseMessage(raw,isBinary);}catch{ws.close(1008,'Device protocol rejected');return;}
      // Receipts do not grant authority by themselves. Match them to this exact
      // authenticated socket without placing stop ACK behind a storage query.
      if(state==='active'&&message.type==='result'){
        if(active.get(context.deviceId)!==entry||!object(message,['type','requestId','outcome'])||typeof message.requestId!=='string'||!object(message.outcome,['state','commandId','leaseId','leaseEpoch','code'])||!['active','accepted','started','completed','stopped','rejected','failed','unknown'].includes(message.outcome.state)){ws.close(1008,'Invalid result');return;}
        const pending=pendingRequests.get(message.requestId);if(!pending)return;
        clearTimeout(pending.timer);pendingRequests.delete(message.requestId);pending.resolve(message.outcome);return;
      }
      if(busy){ws.close(1008,'Unexpected concurrent message');return;}busy=true;
      try{
        if(state==='hello'){
          const hello=validateHello(message,registered.id);
          if(hello.executorEpoch===null&&active.get(registered.id)?.context.executorEpoch)throw Error('CONTROL_CHANNEL_ACTIVE');
          if(hello.executorEpoch!==null&&registered.remoteControlEnabled!==true)throw Error('CONTROL_DISABLED');
          context=Object.freeze({deviceId:registered.id,bootId:hello.bootId,executorEpoch:hello.executorEpoch,certificateId:registered.certificateId,connectionId:randomUUID()});
          challengeExpiry=now()+handshakeTimeoutMs;
          challengeBytes=Buffer.from(JSON.stringify({schema:1,purpose:'device_auth',...context,certificateFingerprint:registered.fingerprint,nonce:randomBytes(32).toString('base64url'),issuedAt:now(),expiresAt:challengeExpiry}));
          state='proof';send({type:'challenge',payloadBase64url:challengeBytes.toString('base64url')});
        }else if(state==='proof'){
          if(!object(message,['type','signatureBase64url'])||message.type!=='proof'||now()>=challengeExpiry||!verify(null,challengeBytes,registered.publicKey,decodeBase64url(message.signatureBase64url,86)))throw Error('INVALID_PROOF');
          if(!await stillRegistered(registered))throw Error('REVOKED');
          if(ws.readyState!==WebSocket.OPEN)throw Error('DEVICE_DISCONNECTED');
          if(!active.has(context.deviceId)&&active.size>=maxDevices)throw Error('CAPACITY');
          const previous=active.get(context.deviceId);
          if(context.executorEpoch===null&&previous?.context.executorEpoch)throw Error('CONTROL_CHANNEL_ACTIVE');
          entry={ws,context,registered,ready:false,pendingRequests};active.set(context.deviceId,entry);
          previous?.ws.close(1008,'Replaced by new device connection');
          state='active';challengeBytes=null;clearTimeout(timer);lastSeen=now();
          send({type:'welcome',context,controlAuthorized:false});events.emit('connected',context);
        }else{
          if(active.get(context.deviceId)?.context.connectionId!==context.connectionId||!await stillRegistered(registered))throw Error('REVOKED');
          if(message.type==='bound'){
            if(!object(message,['type','executorEpoch','hardwareFingerprint','previousStop'])||entry.ready||context.executorEpoch===null||message.executorEpoch!==context.executorEpoch||typeof message.hardwareFingerprint!=='string'||!/^[a-f0-9]{64}$/.test(message.hardwareFingerprint)||!store.registerExecution)throw Error('INVALID_BINDING');
            await store.registerExecution(context,message.hardwareFingerprint,message.previousStop??null);if(ws.readyState!==WebSocket.OPEN||active.get(context.deviceId)!==entry)throw Error('DEVICE_DISCONNECTED');entry.ready=true;send({type:'bound_ack',context,controlAuthorized:false});events.emit('bound',{...context,controlAccepted:true});return;
          }
          if(!object(message,['type','nonce'])||message.type!=='ping'||typeof message.nonce!=='string'||!/^[A-Za-z0-9_-]{1,80}$/.test(message.nonce))throw Error('PROBE_ONLY');
          lastSeen=now();send({type:'pong',nonce:message.nonce,serverTime:now()});
        }
      }catch{ws.close(1008,'Device protocol rejected');}finally{busy=false;}
    });
    ws.lastSeen=()=>lastSeen;
  }
  let sweeping=false;
  const sweep=setInterval(async()=>{
    if(sweeping)return;sweeping=true;
    try{for(const item of active.values()){let valid=false;try{valid=await stillRegistered(item.registered);}catch{/* Storage failure denies a device channel. */}if(!valid||now()-item.ws.lastSeen()>=heartbeatTimeoutMs)item.ws.close(1008,'Device authorization expired');}}
    finally{sweeping=false;}
  },1000);sweep.unref();
  return {server,devices:{events,get(deviceId){const entry=active.get(deviceId);return entry?.ws.readyState===WebSocket.OPEN?{...entry.context,controlAccepted:entry.ready,readOnly:entry.registered.readOnly===true}:null;},async request(deviceId,envelope){
    validateEnvelope(envelope);const item=active.get(deviceId),payload=JSON.parse(decodeBase64url(envelope.payloadBase64url));
    if(!item?.ready||item.ws.readyState!==WebSocket.OPEN||now()>=item.registered.validUntil||!['deviceId','bootId','executorEpoch','connectionId','certificateId'].every(key=>payload[key]===item.context[key]))throw Error('DEVICE_UNAVAILABLE');
    const priorityStop=payload.purpose==='stop'&&payload.opcode==='software_stop';
    if(item.registered.readOnly===true&&payload.purpose==='command'&&!['connect','disconnect'].includes(payload.opcode))throw Error('READ_ONLY_DEVICE');
    if(!priorityStop&&!await stillRegistered(item.registered)||active.get(deviceId)!==item)throw Error('DEVICE_UNAVAILABLE');
    if(item.pendingRequests.size>=(priorityStop?9:8))throw Error('DEVICE_BUSY');
    return new Promise((resolve,reject)=>{
      const requestId=randomUUID(),timeout=payload.purpose==='command'?35000:priorityStop?4000:1500;
      const timer=setTimeout(()=>{item.pendingRequests.delete(requestId);reject(Error('DEVICE_REPLY_UNKNOWN'));},timeout);timer.unref();
      item.pendingRequests.set(requestId,{resolve,reject,timer});
      item.ws.send(JSON.stringify({type:'request',requestId,envelope}),error=>{if(error){clearTimeout(timer);item.pendingRequests.delete(requestId);reject(Error('DEVICE_DISCONNECTED'));}});
    });
  },async send(deviceId,envelope){
    validateEnvelope(envelope);const item=active.get(deviceId);
    if(!item||item.ws.readyState!==WebSocket.OPEN||!await stillRegistered(item.registered)||active.get(deviceId)!==item)throw Error('DEVICE_UNAVAILABLE');
    item.ws.send(JSON.stringify({type:'envelope',envelope}));
  }},async close(){clearInterval(sweep);for(const ws of sockets)ws.terminate();for(const socket of networkSockets)socket.destroy();await new Promise(resolve=>wss.close(resolve));if(server.listening)await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));}};
}
module.exports={createDeviceRelay};
