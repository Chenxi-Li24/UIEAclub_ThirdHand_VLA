'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {parseHTML}=require('linkedom');
const {mountModelWorkspace}=require('../../../apps/web/public/js/workspace-session');
function fixture({live=false,layout='workspace',mode='observe',modelReady=true}={}){
  const {document,window}=parseHTML(fs.readFileSync(path.join(__dirname,'../../../apps/web/public/index.html'),'utf8'));
  const requests=[],view={MutationObserver:window.MutationObserver,location:{hash:'#control'},history:{replaceState(_a,_b,url){view.location.hash=url;}},addEventListener(){},requestAnimationFrame(fn){fn();},localStorage:{getItem(){return null;},setItem(){}},ThirdHandAccountSettings:require('../../../apps/web/public/js/account-settings')};
  const shell=require('../../../apps/web/public/js/'+(layout==='classic'?'classic-shell':'workspace-shell')).mountWorkspace(document,view,{calibrationEntry:null,canOpenPage:id=>id!=='assistant'});
  const arm={jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],joints:[0,90,-90,0,0,0],getJointAngles(){return this.joints.slice();},setJointAngles(value){this.joints=[...value];},setInstallMode(){},getGripperPosition(){return this.gripper;},setGripperPosition(value){this.gripper=value;}};
  const scene={toggleGrid(){},toggleAxes(){},resetView(){},_onResize(){}};
  let time=0;
  let state=null;const listeners=new Set(),stateStore={snapshot:()=>state,subscribe(fn){listeners.add(fn);fn(state);return()=>listeners.delete(fn);}};
  const controls=mountModelWorkspace({document,view,shell,arm,scene,modelReady,stateStore:live?stateStore:undefined,identity:{userId:'local-test-user',role:mode==='admin'?'admin':'observer',mode},sessionClient:{request:async(path,body)=>{requests.push({path,body});return {displayName:'Test user',email:'test@example.invalid',organization:''};}},simulationClock:{now:()=>time,sleep:async ms=>{time+=ms;}}});
  return {document,window,arm,shell,controls,requests,push(next){state=next;for(const fn of listeners)fn(state);},get listeners(){return listeners.size;}};
}
test('observer slider and fixed-pose controls update only their model and cannot activate microphone, SDK or Dummy',async()=>{
  const a=fixture(),b=fixture();
  a.document.getElementById('slider-j0').value='25';a.document.getElementById('slider-j0').dispatchEvent(new a.window.Event('input',{bubbles:true}));
  assert.equal(a.arm.joints[0],25);assert.equal(b.arm.joints[0],0);
  a.document.getElementById('jinput-0').value='';a.document.getElementById('jinput-0').dispatchEvent(new a.window.Event('input',{bubbles:true}));a.document.getElementById('btn-send').click();
  assert.equal(a.arm.joints[0],25,'an invalid empty draft must not be converted into a zero pose');
  a.document.querySelector('[data-simulation-preset="ready"]').click();for(let i=0;i<80;i++)await Promise.resolve();assert.deepEqual(a.arm.joints,[0,90,-90,0,0,0]);
  assert.equal(a.document.getElementById('btn-connect').disabled,true);assert.equal(a.document.getElementById('btn-voice-toggle').disabled,true);
  assert.equal(a.document.getElementById('tab-tcp').disabled,false);
  assert.equal(a.requests.filter(value=>/sdk|control\/|voice|dummy|execution/.test(value.path)).length,0);
  a.document.getElementById('gripper-input').value='50';a.document.getElementById('gripper-input').dispatchEvent(new a.window.Event('input'));
  assert.equal(a.arm.gripper,.5);assert.equal(a.document.getElementById('gripper-slider').value,'0.5');
  a.shell.go('assistant');assert.equal(a.document.getElementById('page-control').hidden,false);
  a.shell.go('calibration');assert.equal(a.document.querySelector('iframe'),null);assert.equal(a.shell.go('control'),true);
  a.controls.dispose();b.controls.dispose();
});

function measured(sequence=1,overrides={}){return {deviceId:'device',fresh:true,status:'connected',value:{sequence,context:{connectionId:'gateway'}},sample:{sourceMode:'hardware',sdkConnected:true,jointPositionRad:[.1,1,-1,.2,0,0],gripper:{positionRatio:.35},flangePositionM:[.3,.1,.4],flangeOrientationEulerRad:[.1,.2,.3]},...overrides};}
function input(f,id,value){const node=f.document.getElementById(id);node.value=value;node.dispatchEvent(new f.window.Event('input',{bubbles:true}));}
function resume(f){const node=f.document.getElementById('chk-sync');node.checked=true;node.dispatchEvent(new f.window.Event('change'));}
for(const layout of ['workspace','classic'])for(const mode of ['observe','admin'])test(`${layout}/${mode}: fresh measured state follows by default, manual drafts survive disconnect and resume explicitly`,()=>{
 const f=fixture({live:true,layout,mode});try{
  f.push(measured());assert.ok(Math.abs(f.arm.joints[0]-.1*180/Math.PI)<1e-9);assert.equal(f.arm.gripper,.35);
  assert.equal(f.document.getElementById('chk-sync').checked,true);assert.equal(f.document.getElementById('chk-sync').disabled,false);
  assert.equal(f.document.getElementById('tcp-x').value,'300');assert.equal(f.document.getElementById('tcp-rx').value,'5.73');
  input(f,'jinput-0','');assert.equal(f.controls.simulation.getState().followingLive,false);
  f.push(measured(2));assert.equal(f.document.getElementById('jinput-0').value,'');
  input(f,'slider-j0','25');f.push(measured(3,{status:'disconnected',fresh:false}));f.push(measured(4));assert.equal(f.arm.joints[0],25);
  resume(f);assert.ok(Math.abs(f.arm.joints[0]-.1*180/Math.PI)<1e-9);
  input(f,'gripper-input','70');f.push(measured(5));assert.equal(f.arm.gripper,.7);assert.equal(f.document.getElementById('chk-sync').checked,false);
  resume(f);input(f,'tcp-x','555');f.push(measured(6));assert.equal(f.document.getElementById('tcp-x').value,'555');
  resume(f);assert.equal(f.document.getElementById('tcp-x').value,'300');assert.equal(f.requests.length,0);
 }finally{f.controls.dispose();}assert.equal(f.listeners,0);
});
test('late model readiness replays latest fresh state; stale, failed, test-source and invalid measurements cannot move model',()=>{
 const f=fixture({live:true,modelReady:false});try{
  f.push(measured());assert.equal(f.arm.joints[0],0);assert.equal(f.document.getElementById('chk-sync').disabled,true);
  f.controls.setReady(true);const before=[...f.arm.joints];assert.notEqual(before[0],0);
  for(const overrides of [{fresh:false},{status:'read_failed'},{sample:{...measured().sample,sourceMode:'simulation'}},{sample:{...measured().sample,sdkConnected:false}},{sample:{...measured().sample,jointPositionRad:[999,0,0,0,0,0]}}]){f.push(measured(2,overrides));assert.deepEqual(f.arm.joints,before);}
  assert.match(f.document.getElementById('model-follow-status').textContent,/cannot be represented/);
  f.push(measured(3));assert.equal(f.document.getElementById('model-follow-status').dataset.state,'following');
  f.push(measured(4,{fresh:false,status:'stale'}));assert.equal(f.document.getElementById('model-follow-status').dataset.state,'waiting');assert.equal(f.document.getElementById('chk-sync').checked,true);
 }finally{f.controls.dispose();}
});
test('waypoint/sequence playback pauses following and cannot be overwritten by fresh telemetry',async()=>{
 const f=fixture({live:true});try{
  f.push(measured());const play=f.controls.simulation.playSequence([{joints:[20,50,-60,0,0,0],gripper:.8,durationMs:100}]);
  f.push(measured(2));await play;assert.deepEqual(f.arm.joints,[20,50,-60,0,0,0]);assert.equal(f.arm.gripper,.8);assert.equal(f.document.getElementById('chk-sync').checked,false);
  f.push(measured(3));assert.equal(f.arm.joints[0],20);assert.equal(f.requests.length,0);
 }finally{f.controls.dispose();}
});
