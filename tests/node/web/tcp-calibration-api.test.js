'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const test=require('node:test');
const {createWebGateway}=require('../../../apps/web/src/server');
const {createTcpCalibrationRoutes}=require('../../../apps/web/src/tcp-calibration/routes');

function fakeSession(){
 let state={schema:'thirdhand-tcp-calibration-session-v1',sessionId:null,revision:0,stage:'idle',fitSamples:[],validationSamples:[]};
 const calls=[];
 return {calls,status:()=>structuredClone(state),async handle(command){
  calls.push(structuredClone(command));
  if(command.type==='start')state={...state,sessionId:'session-1',revision:1,stage:'collecting_fit'};
  else if(command.type==='record_fit')state={...state,revision:state.revision+1,fitSamples:[...state.fitSamples,{id:'fit-1'}]};
  else if(command.type==='delete_fit')state={...state,revision:state.revision+1,fitSamples:[]};
  else if(command.type==='solve')state={...state,revision:state.revision+1,stage:'collecting_validation'};
  else if(command.type==='record_validation')state={...state,revision:state.revision+1,validationSamples:[...state.validationSamples,{id:'validation-1'}]};
  else if(command.type==='derive')state={...state,revision:state.revision+1,stage:'ready_to_finalize',validationReport:{accepted:true},solveReport:{accepted:true},derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1'}};
  else if(command.type==='abort')state={...state,revision:state.revision+1,stage:'aborted'};
  else if(command.type==='new_session')state={...state,sessionId:null,revision:state.revision+1,stage:'idle',fitSamples:[],validationSamples:[]};
  return {accepted:true,state:structuredClone(state)};
 }};
}

async function setup(t,{connected=true,canMutate=()=>true}={}){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'tcp-api-'));
 const session=fakeSession(),storeCalls=[];
 const store={saveSession:s=>storeCalls.push(['save',structuredClone(s)]),
  status:()=>({pendingId:`sha256:${'c'.repeat(64)}`,activeId:`sha256:${'b'.repeat(64)}`,previousActiveId:`sha256:${'a'.repeat(64)}`}),
  finalizePending:s=>{storeCalls.push(['finalize',structuredClone(s)]);return {candidateId:`sha256:${'c'.repeat(64)}`};},
  activate:x=>{storeCalls.push(['activate',structuredClone(x)]);return {activeId:x.candidateId,previousActiveId:x.expectedActiveId};},
  rollback:x=>{storeCalls.push(['rollback',structuredClone(x)]);return {activeId:`sha256:${'a'.repeat(64)}`,previousActiveId:x.expectedActiveId};}};
 const stops=[],teaches=[];const stateSource={snapshot:()=>({connected,locked:!connected}),softwareStop:()=>{stops.push('stop');return true;},teach:command=>{teaches.push(command);return true;},close(){}};
 const routes=createTcpCalibrationRoutes({session,store,stateSource,canMutate});
 const noOp={attach(){},close(){},getRobotState(){return null;},broadcast(){},setGraspInterlock(){}};
 const gateway=createWebGateway({host:'127.0.0.1',port:0,readyFile:path.join(temp,'ready'),
  robotProxy:noOp,visionProxy:noOp,voiceProxy:noOp,
  coordinator:{on(){},status(){return {active:false};},async close(){}},tcpCalibrationRoutes:routes,env:{}});
 const address=await gateway.start();t.after(async()=>{await gateway.close();fs.rmSync(temp,{recursive:true,force:true});});
 return {url:`http://127.0.0.1:${address.port}`,session,store,storeCalls,stops,teaches};
}
const mutation=(url,route,body,{method='POST',origin}={})=>fetch(url+route,{method,
 headers:{'content-type':'application/json',...(origin?{origin}:{})},body:JSON.stringify(body)});
const envelope=(revision,requestId='request-1')=>({sessionId:'session-1',expectedRevision:revision,requestId});

test('runtime config exposes injected calibration and current status',async t=>{
 const {url}=await setup(t);
 const runtime=await (await fetch(url+'/api/runtime-config')).json();
 assert.deepEqual(runtime.tcpCalibration,{ready:true,page:'/tcp-calibration.html'});
 const current=await (await fetch(url+'/api/tcp-calibration/sessions/current')).json();
 assert.equal(current.stage,'idle');
 assert.equal(current.robot.connected,true);
 assert.equal(current.artifacts.previousActiveId,`sha256:${'a'.repeat(64)}`);
});

test('same-origin start validates exact body and body limit',async t=>{
 const {url}=await setup(t);
 const body={requestId:'start-1',operator:'operator-a',measurement:{distanceM:.02,uncertaintyM:.001,toolAxisFlange:[1,0,0]},confirmations:{probeCentered:true,pivotFixed:true,estopReady:true,manualTeachOnly:true}};
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions',body,{origin:'https://attacker.invalid'})).status,403);
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions',{...body,extra:true})).status,400);
 const started=await mutation(url,'/api/tcp-calibration/sessions',body);assert.equal(started.status,201);
 assert.equal((await started.json()).stage,'collecting_fit');
 const huge={...body,operator:'x'.repeat(20_000)};
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions',huge)).status,413);
});

test('fit sample, delete, solve, validation, derive and abort map to session commands',async t=>{
 const {url,session}=await setup(t);
 const start={requestId:'start',operator:'op',measurement:{distanceM:.02,uncertaintyM:.001,toolAxisFlange:[1,0,0]},confirmations:{probeCentered:true,pivotFixed:true,estopReady:true,manualTeachOnly:true}};
 await mutation(url,'/api/tcp-calibration/sessions',start);
 let response=await mutation(url,'/api/tcp-calibration/samples',{...envelope(1,'fit'),contactConfirmed:true,probeUnloaded:true});assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/samples/fit-1',envelope(2,'delete'),{method:'DELETE'});assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/solve',envelope(3,'solve'));assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/verification-samples',{...envelope(4,'verify'),contactConfirmed:true,probeUnloaded:true});assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/derive',envelope(5,'derive'));assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/abort',envelope(6,'abort'));assert.equal(response.status,200);
 assert.deepEqual(session.calls.map(call=>call.type),['start','record_fit','delete_fit','solve','record_validation','derive','abort']);
});

test('stale session revision, malformed sample id, and disconnected sample fail closed',async t=>{
 const connected=await setup(t);
 const start={requestId:'start',operator:'op',measurement:{distanceM:.02,uncertaintyM:.001,toolAxisFlange:[1,0,0]},confirmations:{probeCentered:true,pivotFixed:true,estopReady:true,manualTeachOnly:true}};
 await mutation(connected.url,'/api/tcp-calibration/sessions',start);
 assert.equal((await mutation(connected.url,'/api/tcp-calibration/solve',envelope(0,'stale'))).status,409);
 assert.equal((await mutation(connected.url,'/api/tcp-calibration/samples/%2e%2e',envelope(1,'bad'),{method:'DELETE'})).status,400);
 const disconnected=await setup(t,{connected:false});await mutation(disconnected.url,'/api/tcp-calibration/sessions',start);
 assert.equal((await mutation(disconnected.url,'/api/tcp-calibration/samples',{...envelope(1,'locked'),contactConfirmed:true,probeUnloaded:true})).status,423);
});

test('request replay is idempotent and conflicting reuse returns conflict',async t=>{
 const {url,session}=await setup(t);
 const body={requestId:'same',operator:'op',measurement:{distanceM:.02,uncertaintyM:.001,toolAxisFlange:[1,0,0]},confirmations:{probeCentered:true,pivotFixed:true,estopReady:true,manualTeachOnly:true}};
 const first=await mutation(url,'/api/tcp-calibration/sessions',body);assert.equal(first.status,201);
 const replay=await mutation(url,'/api/tcp-calibration/sessions',body);assert.equal(replay.status,201);
 const conflict=await mutation(url,'/api/tcp-calibration/sessions',{...body,operator:'other'});assert.equal(conflict.status,409);
 const nestedConflict=await mutation(url,'/api/tcp-calibration/sessions',{...body,measurement:{...body.measurement,distanceM:.03}});assert.equal(nestedConflict.status,409);
 assert.equal(session.calls.length,1);
});

test('mutation bodies reject unknown fields instead of silently accepting them',async t=>{
 const {url}=await setup(t);
 const start={requestId:'start',operator:'op',measurement:{distanceM:.02,uncertaintyM:.001,toolAxisFlange:[1,0,0]},confirmations:{probeCentered:true,pivotFixed:true,estopReady:true,manualTeachOnly:true}};
 await mutation(url,'/api/tcp-calibration/sessions',start);
 assert.equal((await mutation(url,'/api/tcp-calibration/solve',{...envelope(1,'solve-extra'),unexpected:true})).status,400);
});

test('finalize defaults to pending while activation and rollback are explicit',async t=>{
 const {url,session,storeCalls}=await setup(t);session.handle=async command=>({accepted:true,state:{...session.status(),sessionId:'session-1',revision:7,stage:'ready_to_finalize',validationReport:{accepted:true},solveReport:{accepted:true},derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1'}}});
 // Seed the fake status through the normal start then override status for storage calls.
 const ready={...session.status(),sessionId:'session-1',revision:7,stage:'ready_to_finalize',validationReport:{accepted:true},solveReport:{accepted:true},derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1'}};
 session.status=()=>structuredClone(ready);
 let response=await mutation(url,'/api/tcp-calibration/finalize',envelope(7,'finalize'));assert.equal(response.status,201);
 assert.equal(storeCalls[0][0],'finalize');assert.equal(storeCalls.some(call=>call[0]==='activate'),false);
 const candidateId=`sha256:${'c'.repeat(64)}`;
 response=await mutation(url,'/api/tcp-calibration/activate',{...envelope(7,'activate'),candidateId,expectedActiveId:null,confirm:true});assert.equal(response.status,200);
 response=await mutation(url,'/api/tcp-calibration/rollback',{...envelope(7,'rollback'),expectedActiveId:candidateId,confirm:true});assert.equal(response.status,200);
});

test('artifact conflicts return a bounded response instead of rejecting the request handler',async t=>{
 const {url,session,store}=await setup(t);
 session.status=()=>({schema:'thirdhand-tcp-calibration-session-v1',sessionId:'session-1',revision:7,stage:'ready_to_finalize',fitSamples:[],validationSamples:[],validationReport:{accepted:true},solveReport:{accepted:true},derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1'}});
 store.activate=()=>{const error=new Error('active_version_conflict');error.code='active_version_conflict';throw error;};
 const response=await mutation(url,'/api/tcp-calibration/activate',{...envelope(7,'conflict'),candidateId:`sha256:${'c'.repeat(64)}`,expectedActiveId:null,confirm:true});
 assert.equal(response.status,409);
 assert.deepEqual(await response.json(),{error:'active_version_conflict'});
});

test('software stop remains available while disconnected and unknown methods fail',async t=>{
 const {url,stops}=await setup(t,{connected:false});
 assert.equal((await mutation(url,'/api/tcp-calibration/software-stop',{requestId:'stop'})).status,200);
 assert.deepEqual(stops,['stop']);
 assert.equal((await fetch(url+'/api/tcp-calibration/solve',{method:'GET'})).status,405);
});

test('teach endpoints expose only start, hold, and keepalive',async t=>{
 const {url,teaches}=await setup(t);
 for(const action of ['start','keepalive','hold'])assert.equal((await mutation(url,`/api/tcp-calibration/teach/${action}`,{requestId:`teach-${action}`})).status,200);
 assert.deepEqual(teaches,['teach_start','teach_keepalive','teach_hold']);
 assert.equal((await mutation(url,'/api/tcp-calibration/teach/move',{requestId:'bad'})).status,400);
});

test('grasp motion ownership rejects calibration writes but never hides software stop',async t=>{
 const {url,teaches}=await setup(t,{canMutate:()=>false});
 const response=await mutation(url,'/api/tcp-calibration/teach/start',{requestId:'busy'});
 assert.equal(response.status,409);assert.equal((await response.json()).error,'robot_control_busy');assert.deepEqual(teaches,[]);
 assert.equal((await mutation(url,'/api/tcp-calibration/software-stop',{requestId:'stop-owned'})).status,200);
});
test('explicit new session preserves artifacts and archives old progress, requiring confirmation and current revision',async t=>{
 const {url,storeCalls,session}=await setup(t);await session.handle({type:'start'});
 const body={...envelope(1,'new'),confirm:true};
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions/new',{...body,confirm:false})).status,400);
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions/new',{...body,expectedRevision:0})).status,409);
 const response=await mutation(url,'/api/tcp-calibration/sessions/new',body);assert.equal(response.status,200);
 assert.equal((await response.json()).stage,'idle');
 assert.deepEqual(storeCalls.map(c=>c[0]),['save','save']);
 assert.equal(storeCalls[0][1].sessionId,'session-1');assert.equal(storeCalls[1][1].sessionId,null);
 const current=await (await fetch(url+'/api/tcp-calibration/sessions/current')).json();
 assert.equal(current.artifacts.activeId,`sha256:${'b'.repeat(64)}`);
 assert.equal((await mutation(url,'/api/tcp-calibration/sessions/new',body)).status,200);
 assert.equal(storeCalls.length,2);
});
