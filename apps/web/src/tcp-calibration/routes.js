'use strict';

function writeJson(response,status,payload){
 const body=JSON.stringify(payload);response.writeHead(status,{'content-type':'application/json; charset=utf-8','content-length':Buffer.byteLength(body),'cache-control':'no-store'});response.end(body);
}
function exact(value,keys){return value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));}
function readJson(request,limit=16*1024){return new Promise((resolve,reject)=>{const chunks=[];let size=0,large=false;request.on('data',chunk=>{size+=chunk.length;if(size>limit)large=true;else chunks.push(chunk);});request.on('end',()=>{if(large)return reject(Object.assign(new Error('body_too_large'),{code:'body_too_large'}));try{resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));}catch{reject(Object.assign(new Error('invalid_json'),{code:'invalid_json'}));}});request.on('error',reject);});}
function digest(value){
 if(Array.isArray(value))return `[${value.map(digest).join(',')}]`;
 if(value&&typeof value==='object')return `{${Object.keys(value).sort().map(key=>`${JSON.stringify(key)}:${digest(value[key])}`).join(',')}}`;
 return JSON.stringify(value);
}

function createTcpCalibrationRoutes({session,store,stateSource}={}){
 if(!session||typeof session.status!=='function'||typeof session.handle!=='function'||!store||!stateSource)throw new TypeError('tcp_calibration_routes_invalid');
 const replays=new Map();
 const config=()=>({ready:true,page:'/tcp-calibration.html'});
 function originAllowed(request){if(!request.headers.origin)return true;try{return new URL(request.headers.origin).host===request.headers.host;}catch{return false;}}
 function envelope(body,status){return body&&typeof body==='object'&&!Array.isArray(body)
  &&body.sessionId===status.sessionId&&Number.isSafeInteger(body.expectedRevision)
  &&typeof body.requestId==='string'&&body.requestId.length>0;}
 function respondReplay(key,body,response){const prior=replays.get(key);if(!prior)return false;if(prior.digest!==digest(body)){writeJson(response,409,{error:'request_id_conflict'});return true;}writeJson(response,prior.status,prior.payload);return true;}
 function remember(key,body,status,payload,response){replays.set(key,{digest:digest(body),status,payload});writeJson(response,status,payload);}
 function storeFailure(error,response){const code=error?.code;const status=code==='candidate_not_found'?404
  :['active_version_conflict','rollback_unavailable'].includes(code)?409
  :code==='candidate_unverified'?400:500;writeJson(response,status,{error:code||'artifact_store_failed'});}
 async function sessionMutation(key,body,response,command,statusCode=200){
  const current=session.status();
  if(!envelope(body,current)){writeJson(response,400,{error:'request_invalid'});return;}
  if(current.revision!==body.expectedRevision){writeJson(response,409,{error:'session_revision_conflict'});return;}
  const result=await session.handle(command);
  if(!result.accepted){const code=result.error==='robot_state_not_recordable'?423:result.error==='request_id_conflict'?409:400;writeJson(response,code,{error:result.error,...(result.reason?{reason:result.reason}:{})});return;}
  try{store.saveSession?.(result.state);}catch(error){storeFailure(error,response);return;}
  remember(key,body,statusCode,result.state,response);
 }
 async function handle(request,response,pathname){
  if(!pathname.startsWith('/api/tcp-calibration/'))return false;
  if(request.method==='GET'&&pathname==='/api/tcp-calibration/sessions/current'){
   try{writeJson(response,200,{...session.status(),robot:stateSource.snapshot(),artifacts:store.status?.()||null});}
   catch(error){storeFailure(error,response);}return true;
  }
  const allowed=new Set([
   'POST /api/tcp-calibration/sessions','POST /api/tcp-calibration/samples','POST /api/tcp-calibration/solve',
   'POST /api/tcp-calibration/verification-samples','POST /api/tcp-calibration/derive','POST /api/tcp-calibration/finalize',
   'POST /api/tcp-calibration/activate','POST /api/tcp-calibration/rollback','POST /api/tcp-calibration/abort',
   'POST /api/tcp-calibration/software-stop','POST /api/tcp-calibration/teach/start',
   'POST /api/tcp-calibration/teach/hold','POST /api/tcp-calibration/teach/keepalive',
  ]);
  const deleteMatch=pathname.match(/^\/api\/tcp-calibration\/samples\/([A-Za-z0-9._:-]+)$/);
  if(!allowed.has(`${request.method} ${pathname}`)&&!(request.method==='DELETE'&&deleteMatch)){
   writeJson(response,request.method==='GET'?405:400,{error:request.method==='GET'?'method_not_allowed':'request_invalid'});return true;
  }
  if(!originAllowed(request)){writeJson(response,403,{error:'origin_not_allowed'});return true;}
  let body;try{body=await readJson(request);}catch(error){writeJson(response,error.code==='body_too_large'?413:400,{error:error.code||'request_invalid'});return true;}
  const requestId=body?.requestId;const key=`${request.method} ${pathname} ${requestId}`;
  if(typeof requestId==='string'&&respondReplay(key,body,response))return true;
  if(pathname==='/api/tcp-calibration/software-stop'){
   if(!exact(body,['requestId'])||typeof requestId!=='string'||!requestId){writeJson(response,400,{error:'request_invalid'});return true;}
   const stopped=stateSource.softwareStop();const payload={accepted:stopped};remember(key,body,stopped?200:503,payload,response);return true;
  }
  const teachMatch=pathname.match(/^\/api\/tcp-calibration\/teach\/(start|hold|keepalive)$/);
  if(teachMatch){
   if(!exact(body,['requestId'])||typeof requestId!=='string'||!requestId){writeJson(response,400,{error:'request_invalid'});return true;}
   try{
    const command=`teach_${teachMatch[1]}`;const accepted=await stateSource.teach(command);
    const payload={accepted,robot:stateSource.snapshot()};remember(key,body,accepted?200:503,payload,response);
   }catch(error){writeJson(response,409,{error:error.message||'teach_failed'});}
   return true;
  }
  if(pathname==='/api/tcp-calibration/sessions'){
   if(!exact(body,['requestId','operator','measurement','confirmations'])){writeJson(response,400,{error:'request_invalid'});return true;}
   const result=await session.handle({type:'start',...body});
   if(!result.accepted){writeJson(response,result.error==='request_id_conflict'?409:400,{error:result.error});return true;}
   try{store.saveSession?.(result.state);}catch(error){storeFailure(error,response);return true;}remember(key,body,201,result.state,response);return true;
  }
  const current=session.status();
  if(!envelope(body,current)){writeJson(response,400,{error:'request_invalid'});return true;}
  if(current.revision!==body.expectedRevision){writeJson(response,409,{error:'session_revision_conflict'});return true;}
  if(['/api/tcp-calibration/samples','/api/tcp-calibration/verification-samples'].includes(pathname)){
   const robot=stateSource.snapshot();
   if(robot.locked){writeJson(response,423,{error:'robot_state_locked',reason:robot.reason||'robot_state_locked'});return true;}
  }
  if(pathname==='/api/tcp-calibration/samples'){
   if(!exact(body,['sessionId','expectedRevision','requestId','contactConfirmed','probeUnloaded'])){writeJson(response,400,{error:'request_invalid'});return true;}
   await sessionMutation(key,body,response,{type:'record_fit',requestId,contactConfirmed:body.contactConfirmed,probeUnloaded:body.probeUnloaded});return true;
  }
  if(deleteMatch){if(!exact(body,['sessionId','expectedRevision','requestId'])){writeJson(response,400,{error:'request_invalid'});return true;}await sessionMutation(key,body,response,{type:'delete_fit',requestId,sampleId:deleteMatch[1]});return true;}
  if(pathname==='/api/tcp-calibration/solve'){if(!exact(body,['sessionId','expectedRevision','requestId'])){writeJson(response,400,{error:'request_invalid'});return true;}await sessionMutation(key,body,response,{type:'solve',requestId});return true;}
  if(pathname==='/api/tcp-calibration/verification-samples'){
   if(!exact(body,['sessionId','expectedRevision','requestId','contactConfirmed','probeUnloaded'])){writeJson(response,400,{error:'request_invalid'});return true;}
   await sessionMutation(key,body,response,{type:'record_validation',requestId,contactConfirmed:body.contactConfirmed,probeUnloaded:body.probeUnloaded});return true;
  }
  if(pathname==='/api/tcp-calibration/derive'){if(!exact(body,['sessionId','expectedRevision','requestId'])){writeJson(response,400,{error:'request_invalid'});return true;}await sessionMutation(key,body,response,{type:'derive',requestId});return true;}
  if(pathname==='/api/tcp-calibration/abort'){if(!exact(body,['sessionId','expectedRevision','requestId'])){writeJson(response,400,{error:'request_invalid'});return true;}await sessionMutation(key,body,response,{type:'abort',requestId});return true;}
  if(pathname==='/api/tcp-calibration/finalize'){
   if(!exact(body,['sessionId','expectedRevision','requestId'])){writeJson(response,400,{error:'request_invalid'});return true;}try{const pending=store.finalizePending(current);remember(key,body,201,pending,response);}catch(error){storeFailure(error,response);}return true;
  }
  if(pathname==='/api/tcp-calibration/activate'){
   if(!exact(body,['sessionId','expectedRevision','requestId','candidateId','expectedActiveId','confirm'])||body.confirm!==true){writeJson(response,400,{error:'request_invalid'});return true;}
   try{const manifest=store.activate({candidateId:body.candidateId,expectedActiveId:body.expectedActiveId});remember(key,body,200,manifest,response);}catch(error){storeFailure(error,response);}return true;
  }
  if(pathname==='/api/tcp-calibration/rollback'){
   if(!exact(body,['sessionId','expectedRevision','requestId','expectedActiveId','confirm'])||body.confirm!==true){writeJson(response,400,{error:'request_invalid'});return true;}
   try{const manifest=store.rollback({expectedActiveId:body.expectedActiveId});remember(key,body,200,manifest,response);}catch(error){storeFailure(error,response);}return true;
  }
  return true;
 }
 return {config,handle,connect(){return stateSource.connect?.();},close(){stateSource.close?.();}};
}
module.exports={createTcpCalibrationRoutes};
