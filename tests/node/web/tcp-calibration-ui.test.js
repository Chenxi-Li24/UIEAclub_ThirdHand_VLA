'use strict';

const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const ROOT=path.resolve(__dirname,'../../..');
const html=()=>fs.readFileSync(path.join(ROOT,'apps/web/public/tcp-calibration.html'),'utf8');
const script=()=>fs.readFileSync(path.join(ROOT,'apps/web/public/js/tcp-calibration.js'),'utf8');

test('standalone page exposes seven Chinese safety-gated stages and main entry',()=>{
 const page=html(),index=fs.readFileSync(path.join(ROOT,'apps/web/public/index.html'),'utf8');
 for(const label of ['第0关：连接与安全检查','第1关：8姿态采集','第2关：求解与诊断','第3关：独立验证','第4关：换算夹爪TCP','第5关：保存候选结果','第6关：激活与回滚'])assert.match(page,new RegExp(label));
 for(const safety of ['人工示教','急停人员','同一个固定尖点','探针没有弯曲','不会自动控制机械臂'])assert.match(page,new RegExp(safety));
 assert.match(index,/href="tcp-calibration\.html"[^>]*>TCP标定</);
});

test('browser controller uses same-origin HTTP and contains no direct robot or camera transport',()=>{
 const source=script();
 for(const forbidden of ['ws://','wss://','move_l','servo','preset','gripper','3100','WebSocket'])assert.doesNotMatch(source,new RegExp(forbidden,'i'));
 assert.match(source,/this\.json\('\/api\/tcp-calibration/);
 assert.doesNotMatch(source,/countdown|score|reward|speed bonus/i);
});

function browser(statuses){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{id,disabled:false,hidden:false,checked:false,value:'',textContent:'',dataset:{},classList:{toggle(){}}});return elements.get(id);};
 const requests=[];let getIndex=0;
 const context={console,crypto:{randomUUID:()=>`request-${requests.length+1}`},
  document:{readyState:'loading',getElementById:element,querySelectorAll:()=>[],addEventListener(){}},
  fetch:async(url,options={})=>{requests.push({url,options});if(url==='/api/runtime-config')return {ok:true,json:async()=>({tcpCalibration:{ready:true}})};
   if(url==='/api/tcp-calibration/sessions/current')return {ok:true,json:async()=>structuredClone(statuses[Math.min(getIndex++,statuses.length-1)])};
   return {ok:true,json:async()=>structuredClone(statuses.at(-1))};},setTimeout,clearTimeout};
 vm.runInNewContext(script()+'\nglobalThis.ExportedWizard=TcpCalibrationWizard;',context);
 return {wizard:new context.ExportedWizard({document:context.document,fetch:context.fetch,crypto:context.crypto}),element,requests};
}

const state=(overrides={})=>({sessionId:'session-1',revision:3,stage:'collecting_fit',fitSamples:[],validationSamples:[],
 robot:{connected:true,healthy:true,stationary:true,stateFresh:true,locked:false,poseFrame:'robot_flange',framePolicyId:`sha256:${'a'.repeat(64)}`,TBaseFlange:[[1,0,0,.2],[0,1,0,.3],[0,0,1,.4],[0,0,0,1]]},...overrides});

test('render shows server revision and locks controls by connection, stage, and sample counts',async()=>{
 const {wizard,element}=browser([state()]);await wizard.init();
 assert.match(element('session-status').textContent,/revision 3/);
 assert.equal(element('record-fit').disabled,false);
 assert.equal(element('solve').disabled,true);
 wizard.render(state({fitSamples:Array.from({length:8},(_,i)=>({id:`fit-${i}`}))}));
 assert.equal(element('solve').disabled,false);
 wizard.render(state({robot:{connected:false,locked:true},fitSamples:Array.from({length:8},()=>({}))}));
 assert.equal(element('record-fit').disabled,true);
});

test('fit and validation controls stay separate and diagnostics are text-labelled',()=>{
 const {wizard,element}=browser([state()]);
 wizard.render(state({stage:'collecting_validation',solveReport:{classification:'yellow',rank:6,singular_values:[4,3,2,1,.5,.1],rms_residual_m:.0025,maximum_residual_m:.0045,worst_sample_id:'fit-4'},validationSamples:[{id:'v1'},{id:'v2'},{id:'v3'}]}));
 assert.equal(element('record-fit').disabled,true);
 assert.equal(element('record-validation').disabled,false);
 assert.equal(element('derive').disabled,true);
 element('confirm-derive').checked=true;wizard.render(wizard.state);
 assert.equal(element('derive').disabled,false);
 assert.match(element('diagnostics').textContent,/黄色/);
 assert.match(element('diagnostics').textContent,/rank 6/);
});

test('refresh before mutation rejects stale local revision without POST',async()=>{
 const {wizard,requests}=browser([state({revision:3}),state({revision:4})]);await wizard.init();
 await assert.rejects(wizard.mutate('/api/tcp-calibration/solve',{}),/stale_local_revision/);
 assert.equal(requests.filter(item=>item.options.method==='POST').length,0);
});

test('derive finalize activate and rollback require explicit confirmations',()=>{
 const {wizard,element}=browser([state()]);
 wizard.render(state({stage:'collecting_validation',validationSamples:[{},{},{}]}));
 assert.equal(element('derive').disabled,true);
 element('confirm-derive').checked=true;wizard.render(wizard.state);assert.equal(element('derive').disabled,false);
 wizard.render(state({stage:'ready_to_finalize',derivedTcp:{},validationReport:{accepted:true}}));
 assert.equal(element('finalize').disabled,true);assert.equal(element('activate').disabled,true);assert.equal(element('rollback').disabled,true);
});

test('restored artifact status keeps rollback available after a page reload',()=>{
 const {wizard,element}=browser([state()]);
 const previousActiveId=`sha256:${'a'.repeat(64)}`;
 wizard.render(state({artifacts:{pendingId:`sha256:${'c'.repeat(64)}`,activeId:`sha256:${'b'.repeat(64)}`,previousActiveId}}));
 assert.equal(element('rollback').disabled,true);
 element('confirm-rollback').checked=true;wizard.render(wizard.state);
 assert.equal(element('rollback').disabled,false);
});
