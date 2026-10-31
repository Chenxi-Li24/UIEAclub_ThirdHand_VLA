'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {parseHTML}=require('linkedom');
const {mountModelWorkspace}=require('../../../apps/web/public/js/workspace-session');
function fixture(){
  const {document,window}=parseHTML(fs.readFileSync(path.join(__dirname,'../../../apps/web/public/index.html'),'utf8'));
  const requests=[],view={MutationObserver:window.MutationObserver,location:{hash:'#control'},history:{replaceState(_a,_b,url){view.location.hash=url;}},addEventListener(){},requestAnimationFrame(fn){fn();},localStorage:{getItem(){return null;},setItem(){}},ThirdHandAccountSettings:require('../../../apps/web/public/js/account-settings')};
  const shell=require('../../../apps/web/public/js/workspace-shell').mountWorkspace(document,view,{calibrationEntry:null,canOpenPage:id=>id!=='assistant'});
  const arm={jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],joints:[0,90,-90,0,0,0],getJointAngles(){return this.joints.slice();},setJointAngles(value){this.joints=[...value];},setInstallMode(){},setGripperPosition(value){this.gripper=value;}};
  const scene={toggleGrid(){},toggleAxes(){},resetView(){},_onResize(){}};
  let time=0;
  const controls=mountModelWorkspace({document,view,shell,arm,scene,identity:{userId:'local-test-user',role:'observer',mode:'observe'},sessionClient:{request:async(path,body)=>{requests.push({path,body});return {displayName:'Test user',email:'test@example.invalid',organization:''};}},simulationClock:{now:()=>time,sleep:async ms=>{time+=ms;}}});
  return {document,window,arm,shell,controls,requests};
}
test('observer slider and fixed-pose controls update only their model and cannot activate microphone, SDK or Dummy',async()=>{
  const a=fixture(),b=fixture();
  a.document.getElementById('slider-j0').value='25';a.document.getElementById('slider-j0').dispatchEvent(new a.window.Event('input',{bubbles:true}));
  assert.equal(a.arm.joints[0],25);assert.equal(b.arm.joints[0],0);
  a.document.getElementById('jinput-0').value='';a.document.getElementById('jinput-0').dispatchEvent(new a.window.Event('input',{bubbles:true}));a.document.getElementById('btn-send').click();
  assert.equal(a.arm.joints[0],25,'an invalid empty draft must not be converted into a zero pose');
  a.document.querySelector('[data-simulation-preset="ready"]').click();for(let i=0;i<80;i++)await Promise.resolve();assert.deepEqual(a.arm.joints,[0,90,-90,0,0,0]);
  assert.equal(a.document.getElementById('btn-connect').disabled,true);assert.equal(a.document.getElementById('btn-voice-toggle').disabled,true);
  assert.equal(a.document.getElementById('tab-tcp').disabled,true);
  assert.equal(a.requests.filter(value=>/sdk|control\/|voice|dummy|execution/.test(value.path)).length,0);
  a.document.getElementById('gripper-input').value='50';a.document.getElementById('gripper-input').dispatchEvent(new a.window.Event('input'));
  assert.equal(a.arm.gripper,.5);assert.equal(a.document.getElementById('gripper-slider').value,'0.5');
  a.shell.go('assistant');assert.equal(a.document.getElementById('page-control').hidden,false);
  a.shell.go('calibration');assert.equal(a.document.querySelector('iframe'),null);assert.equal(a.shell.go('control'),true);
  a.controls.dispose();b.controls.dispose();
});
