'use strict';
const {isIP}=require('node:net');
const {json,readBody}=require('./http');
const {createAiPreviewService}=require('./ai-preview');
function createGuestAi({fetchImpl=fetch,env=process.env,now=Date.now,service}={}){
 const previewAi=service||createAiPreviewService({fetchImpl,env,now});
 return async function serve(req,res,path,{publicOrigin}={}){
  if(path!=='/guest-ai/chat')return false;
  if(req.method!=='POST'){json(res,405,{error:'METHOD_NOT_ALLOWED'},{Allow:'POST'});return true;}
  if(req.headers.origin!==publicOrigin){json(res,403,{error:'ORIGIN_REQUIRED'});return true;}
  if(!service&&!env.GUEST_AI_API_KEY){json(res,503,{error:'AI_UNAVAILABLE'});return true;}
  const remote=req.socket.remoteAddress;
  const ip=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(remote)&&isIP(req.headers['x-real-ip']||'')?req.headers['x-real-ip']:remote;
  let body;try{body=await readBody(req);}catch{json(res,400,{error:'INVALID_INPUT'});return true;}
  try{json(res,200,await previewAi.chat(body,ip));}
  catch(error){const status=[400,429,503].includes(error.status)?error.status:503;json(res,status,{error:status===400?'INVALID_INPUT':status===429?'AI_BUSY':'AI_UNAVAILABLE'},status===429?{'Retry-After':'60'}:{});}
  return true;
 };
}
module.exports={createGuestAi};
