'use strict';
const {pipeline}=require('node:stream/promises');
const {json,requireFields}=require('../http');
const {identityError}=require('../../../../platform/identity/src/errors');
async function exportsRoute({path,request,response,body,principal,exports,sessions}){
  if(path!=='/api/v1/exports'&&!/^\/api\/v1\/exports\/[a-f0-9-]{36}(?:\/download)?$/.test(path))return false;
  if(!exports)throw identityError('EXPORT_SERVICE_UNAVAILABLE');
  if(path==='/api/v1/exports'){
    if(request.method!=='POST')return json(response,405,{error:'METHOD_NOT_ALLOWED'});requireFields(body,['filter','format']);return json(response,202,await exports.create(principal,body));
  }
  if(request.method!=='GET')return json(response,405,{error:'METHOD_NOT_ALLOWED'});
  const id=path.split('/')[4];if(!path.endsWith('/download'))return json(response,200,await exports.status(principal,id));
  const file=await exports.open(principal,id),stream=file.handle.createReadStream();let checking=false;
  const cancel=()=>stream.destroy(),revoked=value=>{if(value.sessionId===principal.sessionId)cancel();};
  sessions.events.on('revoked',revoked);sessions.events.on('unavailable',cancel);
  const timer=setInterval(async()=>{if(checking)return;checking=true;try{const current=await sessions.resolveSession(request);if(current?.sessionId!==principal.sessionId)cancel();}catch{cancel();}finally{checking=false;}},1000);timer.unref();
  response.writeHead(200,{'Content-Type':file.format==='csv'?'text/csv; charset=utf-8':'application/x-ndjson; charset=utf-8','Content-Disposition':`attachment; filename="thirdhand-${id}.${file.format==='csv'?'csv':'ndjson'}"`,'Content-Length':file.size,'Cache-Control':'no-store','X-Export-SHA256':file.digest});
  try{await pipeline(stream,response);}catch{response.destroy();}finally{clearInterval(timer);sessions.events.off('revoked',revoked);sessions.events.off('unavailable',cancel);await file.handle.close().catch(()=>{});}
  return true;
}
module.exports={exportsRoute};
