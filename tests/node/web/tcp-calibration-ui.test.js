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
 for(const safety of ['人工示教','急停人员','同一个固定尖点','探针没有弯曲','带重力补偿'])assert.match(page,new RegExp(safety));
 for(const label of ['进入拖动示教','锁定当前姿态','20 + 60 = 80 mm'])assert.match(page,new RegExp(label.replace('+','\\+')));
 assert.match(index,/href="tcp-calibration\.html"[^>]*>TCP标定</);
});

test('browser controller uses same-origin HTTP and contains no direct robot or camera transport',()=>{
 const source=script();
 for(const forbidden of ['ws://','wss://','move_l','servo','preset','gripper','3100','WebSocket'])assert.doesNotMatch(source,new RegExp(forbidden,'i'));
 assert.match(source,/this\.json\('\/api\/tcp-calibration/);
 assert.doesNotMatch(source,/countdown|score|reward|speed bonus/i);
});

test('browser fetch is invoked without rebinding the native receiver',async()=>{
 const elements=new Map();
 const document={getElementById:id=>{if(!elements.has(id))elements.set(id,{id});return elements.get(id);},querySelectorAll:()=>[],addEventListener(){}};
 const nativeLikeFetch=function(){
  assert.equal(this,undefined);
  return Promise.resolve({ok:true,json:async()=>({ready:true})});
 };
 const context={console,document,fetch:nativeLikeFetch,crypto:{randomUUID:()=> 'request-1'},setTimeout,clearTimeout};
 vm.runInNewContext(script()+'\nglobalThis.ExportedWizard=TcpCalibrationWizard;',context);
 const wizard=new context.ExportedWizard({document,fetch:nativeLikeFetch,crypto:context.crypto});
 assert.deepEqual(await wizard.json('/probe'),{ready:true});
});

test('request IDs work on HTTP origins without crypto.randomUUID',()=>{
 let next=0;
 const crypto={getRandomValues(bytes){for(let i=0;i<bytes.length;i++)bytes[i]=(next++)&255;return bytes;}};
 const context={console,document:{addEventListener(){}},fetch:async()=>{},crypto,setTimeout,clearTimeout};
 vm.runInNewContext(script()+'\nglobalThis.ExportedWizard=TcpCalibrationWizard;',context);
 const wizard=new context.ExportedWizard({document:context.document,fetch:context.fetch,crypto});
 assert.match(wizard.requestId(),/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});

function browser(statuses){
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{id,disabled:false,hidden:false,checked:false,value:'',textContent:'',dataset:{},append(){},classList:{toggle(){}}});return elements.get(id);};
 const requests=[];let getIndex=0;
 const context={console,crypto:{randomUUID:()=>`request-${requests.length+1}`},
  document:{readyState:'loading',getElementById:element,createElement:()=>({}),querySelectorAll:()=>[],addEventListener(){}},
  fetch:async(url,options={})=>{requests.push({url,options});if(url==='/api/runtime-config')return {ok:true,json:async()=>({tcpCalibration:{ready:true}})};
   if(url==='/api/tcp-calibration/sessions/current')return {ok:true,json:async()=>structuredClone(statuses[Math.min(getIndex++,statuses.length-1)])};
   return {ok:true,json:async()=>structuredClone(statuses.at(-1))};},setTimeout,clearTimeout};
 vm.runInNewContext(script()+'\nglobalThis.ExportedWizard=TcpCalibrationWizard;',context);
 return {wizard:new context.ExportedWizard({document:context.document,fetch:context.fetch,crypto:context.crypto}),element,requests};
}

const state=(overrides={})=>({sessionId:'session-1',revision:3,stage:'collecting_fit',fitSamples:[],validationSamples:[],
 robot:{connected:true,healthy:true,stationary:true,stateFresh:true,locked:false,teachSupported:true,poseFrame:'robot_flange',framePolicyId:`sha256:${'a'.repeat(64)}`,TBaseFlange:[[1,0,0,.2],[0,1,0,.3],[0,0,1,.4],[0,0,0,1]]},...overrides});

test('resuming a session hides setup and cannot submit a duplicate start',async()=>{
 const {wizard,element,requests}=browser([state({operator:'Fanxy',measurement:{distanceM:.08,uncertaintyM:.001,toolAxisFlange:[1,0,0]}})]);
 await wizard.init();
 assert.equal(element('start-session').disabled,true);
 assert.equal(element('setup-fields').hidden,true);
 assert.match(element('session-summary').textContent,/Fanxy.*80/);
 await wizard.start();
 assert.equal(requests.some(item=>item.options.method==='POST'),false);
});
test('empty samples cannot be deleted and the next step explains the disconnected state',async()=>{
 const {wizard,element,requests}=browser([state({robot:{connected:false,locked:true}})]);
 await wizard.init();
 assert.equal(element('delete-fit').disabled,true);
 assert.match(element('next-step').textContent,/连接/);
 await element('delete-fit').onclick();
 assert.equal(requests.some(item=>item.options.method==='DELETE'),false);
 assert.doesNotMatch(element('message').textContent,/request_invalid/);
});
test('progress and next instruction follow confirmed teach and sample state',()=>{
 const {wizard,element}=browser([state()]);
 wizard.render(state({fitSamples:[{id:'one'}],robot:{...state().robot,teachActive:true}}));
 assert.match(element('fit-progress').textContent,/1.*8/);
 assert.match(element('next-step').textContent,/锁定/);
 wizard.render(state({robot:{...state().robot,teachSupported:true}}));
 assert.match(element('next-step').textContent,/进入拖动/);
 wizard.message('duplicate_orientation');
 assert.match(element('message').textContent,/角度/);
});

test('LAN HTTP can generate request IDs when randomUUID is unavailable',()=>{
 const {wizard}=browser([state()]);
 const {webcrypto}=require('node:crypto');
 wizard.crypto={getRandomValues:bytes=>webcrypto.getRandomValues(bytes)};
 const first=wizard.requestId(),second=wizard.requestId();
 assert.match(first,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
 assert.notEqual(first,second);
});

test('zero uncertainty is rejected before submitting a calibration session',async()=>{
 const {wizard,element,requests}=browser([state()]);
 element('tool-axis').value='1,0,0';element('needle-mm').value='20';element('distance-mm').value='60';
 element('uncertainty-mm').value='0';
 await assert.rejects(wizard.start(),/测量不确定度/);
 assert.equal(requests.length,0);
});

test('teach mode blocks both sample types and offers hold based on server state',()=>{
 const {wizard,element}=browser([state()]);
 wizard.render(state({stage:'collecting_validation',robot:{...state().robot,teachActive:true,teachSupported:true}}));
 assert.equal(element('teach-start').disabled,true);
 assert.equal(element('teach-hold').disabled,false);
 assert.equal(element('record-validation').disabled,true);
 assert.equal(element('record-fit').disabled,true);
 assert.match(element('robot-status').textContent,/0 阻尼/);
});
test('teach rejection does not claim an active mode or start heartbeats',async()=>{
 const {wizard,element}=browser([state()]);wizard.render(state());
 element('support-ready').checked=true;
 wizard.fetch=async()=>({ok:false,json:async()=>({error:'robot_not_connected'})});
 await assert.rejects(wizard.teach('start'),/robot_not_connected/);
 assert.equal(wizard.teaching,false);assert.equal(wizard.teachTimer,null);
 assert.equal(element('record-fit').disabled,true);
});

test('render shows server revision and locks controls by connection, stage, and sample counts',async()=>{
 const {wizard,element}=browser([state()]);await wizard.init();
 assert.match(element('session-status').textContent,/revision 3/);
 assert.equal(element('record-fit').disabled,true);
 wizard.captureHeld=true;element('contact-ready').checked=element('pose-stable').checked=true;wizard.render(wizard.state);
 assert.equal(element('record-fit').disabled,false);
 assert.equal(element('solve').disabled,true);
 wizard.render(state({fitSamples:Array.from({length:8},(_,i)=>({id:`fit-${i}`}))}));
 assert.equal(element('solve').disabled,false);
 wizard.render(state({robot:{connected:false,locked:true},fitSamples:Array.from({length:8},()=>({}))}));
 assert.equal(element('record-fit').disabled,true);
});

test('fit and validation controls stay separate and diagnostics are text-labelled',()=>{
 const {wizard,element}=browser([state()]);
 wizard.captureHeld=true;
 element('contact-ready').checked=element('pose-stable').checked=true;
 wizard.render(state({stage:'collecting_validation',solveReport:{classification:'yellow',rank:6,singular_values:[4,3,2,1,.5,.1],rms_residual_m:.0025,maximum_residual_m:.0045,worst_sample_id:'fit-4'},validationSamples:[{id:'v1'},{id:'v2'},{id:'v3'}]}));
 assert.equal(element('record-fit').disabled,true);
 assert.equal(element('record-validation').disabled,false);
 assert.equal(element('derive').disabled,true);
 element('confirm-derive').checked=true;wizard.render(wizard.state);
 assert.equal(element('derive').disabled,false);
 assert.match(element('diagnostics').textContent,/黄色/);
 assert.match(element('diagnostics').textContent,/rank 6/);
});

test('validation stage can delete the selected validation sample',async()=>{
 const current=state({stage:'collecting_validation',validationSamples:[{id:'validation-1'}]});
 const {wizard,element,requests}=browser([current]);
 await wizard.init();
 element('validation-sample').value='validation-1';

 await element('delete-validation').onclick();

 const deletion=requests.find(item=>item.options.method==='DELETE');
 assert.equal(deletion.url,'/api/tcp-calibration/verification-samples/validation-1');
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

test('two-person capture requires fresh human confirmations and consumes them after each sample',async()=>{
 const {wizard,element,requests}=browser([state()]);await wizard.init();
 assert.equal(element('teach-start').disabled,true);
 await assert.rejects(wizard.teach('start'),/搭档/);
 await assert.rejects(wizard.record('fit'),/本次/);
 assert.equal(requests.some(x=>x.options.method==='POST'),false);
 element('support-ready').checked=true;wizard.render(wizard.state);
 assert.equal(element('teach-start').disabled,false);
 element('contact-ready').checked=element('pose-stable').checked=true;wizard.render(wizard.state);
 assert.equal(element('record-fit').disabled,true);
 await assert.rejects(wizard.record('fit'),/确认本次锁定/);
 wizard.captureHeld=true;wizard.render(wizard.state);
 await wizard.record('fit');
 assert.equal(requests.filter(x=>x.options.method==='POST').length,1);
 assert.equal(element('contact-ready').checked,false);
 assert.equal(element('pose-stable').checked,false);
 assert.equal(element('record-fit').disabled,true);
});

test('stale contact checks cannot enable recording before a confirmed hold',async()=>{
 const {wizard,element,requests}=browser([state()]);await wizard.init();
 element('contact-ready').checked=element('pose-stable').checked=true;
 wizard.render(wizard.state);
 assert.equal(element('record-fit').disabled,true);
 await assert.rejects(wizard.record('fit'),/确认本次锁定/);
 assert.equal(requests.some(item=>item.options.method==='POST'),false);
});

test('already positioned arm can confirm hold and record without entering drag again',async()=>{
 const {wizard,element}=browser([state()]);await wizard.init();
 const calls=[];
 wizard.fetch=async(url,options={})=>{
  calls.push({url,options});
  return {ok:true,json:async()=>url.endsWith('/teach/hold')
   ?{accepted:true,robot:{...state().robot,teachActive:false}}:state()};
 };
 assert.equal(element('teach-hold').disabled,true);
 element('support-ready').checked=true;wizard.render(wizard.state);
 assert.equal(element('teach-hold').disabled,false);
 await wizard.teach('hold');
 element('contact-ready').checked=element('pose-stable').checked=true;wizard.render(wizard.state);
 assert.equal(element('record-fit').disabled,false);
 await wizard.record('fit');
 assert.deepEqual(calls.filter(c=>c.options.method==='POST').map(c=>c.url),
  ['/api/tcp-calibration/teach/hold','/api/tcp-calibration/samples']);
 assert.equal(element('record-fit').disabled,true);
});

test('pre-submit refresh revokes contact confirmations when the pose starts moving',async()=>{
 const {wizard,element,requests}=browser([state(),state({robot:{...state().robot,
  stationary:false,locked:true,reason:'pose_not_stable'}})]);
 await wizard.init();wizard.captureHeld=true;
 element('contact-ready').checked=element('pose-stable').checked=true;
 await assert.rejects(wizard.record('fit'),/pose_not_stable/);
 assert.equal(requests.some(r=>r.options.method==='POST'),false);
 assert.equal(element('contact-ready').checked,false);
});

test('stale, moving or teaching feedback clears contact confirmation and missing teach service blocks capture',async()=>{
 const {wizard,element,requests}=browser([state()]);
 for(const change of [{stateFresh:false},{stationary:false},{teachActive:true}]){
  element('contact-ready').checked=element('pose-stable').checked=true;
  wizard.render(state({robot:{...state().robot,...change}}));
  assert.equal(element('record-fit').disabled,true);
  assert.equal(element('pose-stable').checked,false);
 }
 wizard.render(state({robot:{...state().robot,teachSupported:false}}));
 element('contact-ready').checked=element('pose-stable').checked=true;wizard.render(wizard.state);
 assert.equal(element('record-fit').disabled,true);
 assert.equal(element('service-warning').hidden,false);
 await assert.rejects(wizard.record('fit'),/robot_state_locked/);
 assert.equal(requests.length,0);
});
