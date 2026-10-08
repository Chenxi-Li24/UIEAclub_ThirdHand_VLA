'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function ui({fetchImpl}={}){
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:'',classList:{toggle(){}}});return elements.get(id);};
 const sent=[];const context={console:{log(){},warn(){},error(){}},THREE:{},window:{},
  document:{readyState:'loading',addEventListener(){},getElementById:get,querySelectorAll:()=>[]},
  fetch:fetchImpl||(async(route,options)=>{sent.push({route,body:JSON.parse(options.body)});return {ok:true,json:async()=>({phase:'depth_acquiring',active:true,sessionId:'one'})};}),setTimeout,clearTimeout};
 const source=fs.readFileSync(path.join(__dirname,'../../../apps/web/public/js/main.js'),'utf8').replace(/^import .*\r?$/gm,'');
 vm.runInNewContext(source+'\nglobalThis.TestControls=UIControls;',context);
 const c=Object.create(context.TestControls.prototype);Object.assign(c,{webGraspEnabled:true,webGraspStatus:{active:false},robotStateReady:true,
  selectedVisionTarget:{stableId:2,actionable:false},visionConfigExecutionEnabled:false,visionTargetExecutionEnabled:false,graspPhase:'idle',
  _renderActiveDepthStatus(){},_log(){}});return {c,get,sent};
}
test('new grasp button uses its own capability rather than false imported gates',()=>{
 const {c,get}=ui();c._updateVisionControls();assert.equal(get('btn-grasp-start').disabled,false);assert.equal(get('btn-grasp-next').disabled,true);
 c.webGraspStatus={active:true};c._updateVisionControls();assert.equal(get('btn-grasp-start').disabled,true);assert.equal(get('btn-grasp-cancel').disabled,false);
});
test('new UI requests one server-owned session and renders returned status',async()=>{
 const {c,sent}=ui();await c._requestWebGrasp('/api/grasp/start',{stableId:2,requestId:'r1'});
 assert.deepEqual(sent,[{route:'/api/grasp/start',body:{stableId:2,requestId:'r1'}}]);assert.equal(c.webGraspStatus.sessionId,'one');
});

test('grasp panel renders measured TCP, base target, current segment progress and physical verification boundary',()=>{
 const {c,get}=ui();c.webGraspConfig={enabled:true,tcp:{source:'measured',id:'tcp-version-A',T_flange_grasp_tcp:[[1,0,0,.09],[0,1,0,.02],[0,0,1,.01],[0,0,0,1]],forwardBackoffM:0}};
 c._applyWebGraspStatus({phase:'approach',active:true,stableId:2,depthValidFrames:3,tcp:c.webGraspConfig.tcp,
  targetM:[.4,0,.2],progress:{completed:2,total:10},completedSegments:30,plan:{contact:{position:[.48334,-.02,.19]}},holding:false});
 assert.match(get('grasp-tcp').textContent,/实测.*tcp-version-A/);assert.match(get('grasp-target-position').textContent,/400.0.*0.0.*200.0/);
 assert.match(get('grasp-progress').textContent,/2.*10/);assert.match(get('grasp-phase').textContent,/接近/);
 c._applyWebGraspStatus({...c.webGraspStatus,phase:'complete',active:false,holding:true,result:{pipelineComplete:true,physicalGraspVerified:false}});
 assert.match(get('grasp-result').textContent,/流程完成.*实物.*未确认/);
});
test('configuration failure is visible and a rejected request does not fake an active workflow',async()=>{
 const {c,get}=ui({fetchImpl:async()=>({ok:false,json:async()=>({error:'tcp_frame_policy_mismatch'})})});c.webGraspEnabled=false;c.webGraspConfig={enabled:false,reason:'tcp_frame_policy_mismatch'};c._updateVisionControls();
 assert.match(get('vision-lock-reason').textContent,/tcp_frame_policy_mismatch/);
 await c._requestWebGrasp('/api/grasp/start',{stableId:2,requestId:'one'});
 assert.equal(c.webGraspStatus.active,false);assert.match(get('grasp-result').textContent,/tcp_frame_policy_mismatch/);
});
test('reconnect refreshes runtime and current grasp status without relying on prior broadcasts',async()=>{
 const {c,get}=ui();const calls=[];c._graspFetch=async route=>{calls.push(route);return {ok:true,json:async()=>route==='/api/runtime-config'
  ?{grasp:{enabled:true,tcp:{source:'measured',id:'reloaded',T_flange_grasp_tcp:[[1,0,0,.1],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}}}
  :{phase:'lifting',active:true,stableId:2,sessionId:'running',progress:{completed:1,total:10}}};};
 await c._refreshWebGrasp();assert.deepEqual(calls,['/api/runtime-config','/api/grasp/status']);
 assert.equal(c.webGraspStatus.sessionId,'running');assert.match(get('grasp-phase').textContent,/抬升/);
});
test('pending stop displays confirmation in progress and retains workflow controls',()=>{
 const {c,get}=ui();c._applyWebGraspStatus({phase:'stopping',active:true,interlocked:true,sessionId:'one',reason:'operator_stop'});
 assert.match(get('grasp-phase').textContent,/等待.*确认/);
 assert.equal(get('btn-grasp-start').disabled,true);assert.equal(get('btn-grasp-cancel').disabled,false);
});
