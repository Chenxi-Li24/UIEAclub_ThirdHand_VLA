'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function ui(){
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,{disabled:false,textContent:'',classList:{toggle(){}}});return elements.get(id);};
 const sent=[];const context={console:{log(){},warn(){},error(){}},THREE:{},window:{},
  document:{readyState:'loading',addEventListener(){},getElementById:get,querySelectorAll:()=>[]},
  fetch:async(route,options)=>{sent.push({route,body:JSON.parse(options.body)});return {ok:true,json:async()=>({phase:'depth_acquiring',active:true,sessionId:'one'})};},setTimeout,clearTimeout};
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
