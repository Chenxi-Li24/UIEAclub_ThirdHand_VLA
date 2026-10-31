'use strict';
const {json,requireFields}=require('../http');
const {identityError}=require('../../../../platform/identity/src/errors');
const {authorize}=require('../../../../platform/identity/src/policy');
async function mediaRoute({path,request,response,body,principal,mediaService}){
  if(!path.startsWith('/api/v1/media/'))return false;
  if(!authorize(principal,'video.view').ok)throw identityError('FORBIDDEN');
  if(!mediaService)throw identityError('MEDIA_UNAVAILABLE');
  if(path==='/api/v1/media/status'&&request.method==='GET'){
    const deviceId=new URL(request.url,'http://localhost').searchParams.get('deviceId');
    if(!/^[a-f0-9-]{36}$/i.test(deviceId||''))throw identityError('INVALID_INPUT');return json(response,200,mediaService.status(deviceId));
  }
  if(request.method!=='POST')return json(response,405,{error:'METHOD_NOT_ALLOWED'});
  if(path==='/api/v1/media/view'){requireFields(body,['deviceId']);return json(response,200,await mediaService.issueViewGrant(principal,request,body));}
  if(path==='/api/v1/media/frame'){requireFields(body,['viewerId','frameId','capturedAtUs']);return json(response,200,await mediaService.reportViewFrame(principal,body));}
  if(path==='/api/v1/media/close'){requireFields(body,['viewerId']);return json(response,200,await mediaService.closeViewer(principal,body.viewerId));}
  return false;
}
async function mediaSignalRoute({path,request,response,sessions,mediaService,publicOrigin,trustProxyLoopback}){
  if(path!=='/internal/v1/media-auth')return false;
  if(!trustProxyLoopback||!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(request.socket.remoteAddress)||request.method!=='GET'||!mediaService)throw identityError('FORBIDDEN');
  const original=request.headers['x-original-uri'];if(typeof original!=='string'||original.length>10000)throw identityError('FORBIDDEN');
  const url=new URL(original,publicOrigin);if(url.origin!==publicOrigin||!/^\/media\/rtc(?:\/v1)?(?:\/validate)?$/.test(url.pathname))throw identityError('FORBIDDEN');
  const tokens=url.searchParams.getAll('access_token'),authorization=request.headers['x-original-authorization'];
  const native=typeof authorization==='string'&&authorization.length<=8200?/^Bearer ([A-Za-z0-9_.-]+)$/.exec(authorization):null;
  if(native){
    // Native Python/Rust SDKs put their camera credential in Authorization.
    // This path never substitutes for a browser's session or accepts mixed credentials.
    if(tokens.length||request.headers.cookie||request.headers['x-original-origin'])throw identityError('FORBIDDEN');
  }else if(authorization||tokens.length!==1)throw identityError('FORBIDDEN');
  const principal=native?null:await sessions.resolveSession(request),result=await mediaService.authorizeSignaling(native?native[1]:tokens[0],principal);
  if(native&&result.kind!=='publisher')throw identityError('FORBIDDEN');
  const originalOrigin=request.headers['x-original-origin'];
  // Browser WebSockets carry Origin. The SDK's same-origin diagnostic fetch may
  // omit it; only that exact validation route accepts trusted Fetch Metadata.
  const sameOriginValidation=url.pathname.endsWith('/validate')&&!originalOrigin&&request.headers['x-original-sec-fetch-site']==='same-origin';
  if(result.kind==='viewer'&&originalOrigin!==publicOrigin&&!sameOriginValidation)throw identityError('FORBIDDEN');
  response.writeHead(204,{'Cache-Control':'no-store'});response.end();return true;
}
module.exports={mediaRoute,mediaSignalRoute};
