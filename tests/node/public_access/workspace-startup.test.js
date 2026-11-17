'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {parseHTML}=require('linkedom');
const workspace=require('../../../apps/web/public/js/workspace-session');
const camera=require('../../../apps/web/public/js/camera-view');
const preferences=require('../../../apps/web/public/js/preferences');
const security=require('../../../apps/web/public/js/account-security');
const shellApi=require('../../../apps/web/public/js/workspace-shell');
const startup=require('../../../apps/web/public/js/workspace-startup');
function fixture({slowModules=false,slowProfile=false,mode='observe',locale='en',measurement=null}={}){
  const {document,window}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  let resolveModel,rejectModel,monitoring=false,fits=0;
  const loading=new Promise((resolve,reject)=>{resolveModel=resolve;rejectModel=reject;});
  const aiCalls=[];const requests=[],events=new Map(),identity={userId:'test',sessionId:'test-session',role:mode==='admin'?'admin':'observer',mode,csrfToken:'fixture',displayName:'Startup user'};
  const session={load:async()=>identity,request:async(path,body,options)=>{requests.push(path);if(path==='/api/v1/ai/preview'){aiCalls.push({body,options});return {reply:'Ready for a model preview.',joints:null,gripper:0,mode:'preview-only'};}if(path==='/api/v1/me/profile'&&slowProfile)return new Promise(()=>{});return path==='/api/v1/tutorial'?{state:{status:'completed'}}:path==='/api/v1/me/waypoints'?{waypoints:[],limit:100}:path.includes('preferences')?{locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:0}:{};},startMonitoring(){monitoring=true;},close(){}};
  const view={document,Event:window.Event,location:{hash:'#vision',assign(){}},history:{replaceState(){}},localStorage:{getItem(){return null;},setItem(){}},MutationObserver:window.MutationObserver,addEventListener:(name,fn)=>events.set(name,fn),setInterval(){return 1;},clearInterval(){},ThirdHandAccountSettings:require('../../../apps/web/public/js/account-settings')};
  view.requestAnimationFrame=fn=>fn();view.setTimeout=setTimeout;view.clearTimeout=clearTimeout;
  const data=document.createElement('script');data.id='workspace-bootstrap';data.type='application/json';data.textContent=JSON.stringify({identity,preferences:{locale,themeId:'light',layoutId:'workspace',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:1}});document.head.append(data);
  class Arm{
    constructor(){this.loadingPromise=loading;this.geometryReady=Promise.resolve();this.mount={};this.jointLimits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];this.joints=[0,0,0,0,0,0];}
    getJointAngles(){return this.joints.slice();}setJointAngles(value){this.joints=[...value];}setMeasuredJointAngles(value){this.joints=[...value];}setGripperPosition(value){this.gripper=value;}getGripperPosition(){return this.gripper;}setInstallMode(){}
  }
  class Scene{constructor(){this.scene={};}fitModel(){fits++;}_onResize(){}toggleGrid(){}toggleAxes(){}resetView(){}}
  Object.assign(view,{
    ThirdHandWorkspaceSession:{...workspace,createWorkspaceSession:()=>session},ThirdHandPreferences:preferences,
    ThirdHandTutorialAdapter:{scopedTutorialView:()=>view},ThirdHandWorkspace:{mountWorkspace(...args){return {...shellApi.mountWorkspace(...args),installOnboarding(){}};}},
    ThirdHandWorkspaceNavigation:require('../../../apps/web/public/js/workspace-navigation'),
    ThirdHandRobotViewer:{createRobotViewer:()=>({SceneManager:Scene,ArmModel:Arm})},ThirdHandAccountSecurity:security,ThirdHandCameraView:camera,
    ThirdHandDeviceState:{mountDeviceState(){return {store:{snapshot:()=>measurement,subscribe(fn){fn(measurement);return ()=>{};}},dispose(){}};}},ThirdHandAiPreviewChat:require('../../../apps/web/public/js/ai-preview-chat'),ThirdHandAdminControl:{mountAdminControl(){return {dispose(){}};}},ThirdHandModelWaypoints:require('../../../apps/web/public/js/model-waypoints'),ThirdHandOnboarding:{}});
  const boot=startup.start({document,view,loadModel:()=>slowModules?new Promise(()=>{}):Promise.resolve({createViewer:()=>({SceneManager:Scene,ArmModel:Arm})})});
  return {document,window,aiCalls,requests,boot,resolveModel,rejectModel,get monitoring(){return monitoring;},get fits(){return fits;},dispose(){events.get('pagehide')?.();}};
}
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
test('authenticated modern startup keeps the current shell navigation and account/data access for both roles',async()=>{
 for(const mode of ['observe','admin']){
  const f=fixture({slowModules:true,mode});await f.boot;await flush();
  try{
   for(const [id,label]of [['overview','System Check'],['control','Digital Twin'],['vision','Vision tasks'],['system','System']]){
    const button=f.document.querySelector(`#workspace-nav [data-page="${id}"]`);
    assert.equal(button.querySelector('.nav-label').textContent,label);
    assert.equal(button.getAttribute('aria-label'),label);
    assert.equal(f.document.getElementById('heading-'+id).textContent,label);
   }
   assert.equal(f.document.querySelector('[data-workspace-entry="data"]').getAttribute('href'),'/history');
   assert.ok(f.document.getElementById('workspace-account'));assert.ok(f.document.getElementById('workspace-logout'));
   for(const id of ['calibration','assistant'])assert.equal(f.document.querySelector(`#workspace-nav [data-page="${id}"]`).hidden,mode!=='admin');
   f.document.documentElement.lang='en';await new Promise(setImmediate);
   assert.equal(f.document.querySelector('[data-page="control"] .nav-label').textContent,'Digital Twin');
   assert.equal(f.requests.some(path=>/sdk|control\/command/.test(path)),false);
  }finally{f.dispose();}
 }
});
test('slow model geometry does not block account, camera, or session monitoring; only model controls wait',async()=>{
  const f=fixture();await flush();
  try{
    assert.equal(f.document.getElementById('workspace-mode').textContent,'Observer · model simulation');
    assert.ok(f.document.getElementById('workspace-logout'),'logout must be available before geometry finishes');
    assert.ok(f.document.querySelector('.cloud-camera-controls'),'camera must initialize before geometry finishes');
    assert.equal(f.document.querySelector('.cloud-camera-controls button').disabled,false);
    assert.equal(f.monitoring,true);
    assert.equal(f.document.getElementById('slider-j0').disabled,true);
    assert.ok(f.document.getElementById('model-waypoints'));
    assert.equal(f.document.getElementById('save-model-waypoint').disabled,true);
    f.resolveModel();await f.boot;await flush();
    assert.equal(f.fits,1);assert.equal(f.document.getElementById('slider-j0').disabled,false);
    assert.equal(f.document.getElementById('save-model-waypoint').disabled,false);
    assert.equal(f.document.getElementById('btn-connect').disabled,true);
    assert.equal(f.requests.some(path=>/sdk|control\/command/.test(path)),false);
  }finally{f.resolveModel();await f.boot;f.dispose();}
});
test('even stalled Three modules and full profile cannot delay the shell, initial account name, camera or logout',async()=>{
  const f=fixture({slowModules:true,slowProfile:true});await f.boot;await flush();
  try{
    assert.equal(f.document.getElementById('app').dataset.ready,'true');
    assert.equal(f.document.querySelector('.account-entry-copy strong').textContent,'Startup user');
    assert.equal(f.document.querySelector('.account-entry .account-avatar').textContent,'ST');
    assert.ok(f.document.getElementById('workspace-logout'));assert.ok(f.document.querySelector('.cloud-camera-controls'));
    assert.equal(f.monitoring,true);assert.equal(f.requests.includes('/api/v1/me/preferences'),false);
    assert.equal(f.document.getElementById('btn-connect').disabled,true);
  }finally{f.dispose();}
});
test('failed model geometry leaves camera and sign-out available while live robot control stays disabled',async()=>{
  const f=fixture();await flush();f.rejectModel(Error('fixture model unavailable'));await f.boot;await flush();
  try{
    assert.ok(f.document.getElementById('workspace-logout'));
    assert.ok(f.document.querySelector('.cloud-camera-controls'));
    assert.equal(f.document.querySelector('.cloud-camera-controls button').disabled,false);
    assert.equal(f.document.getElementById('slider-j0').disabled,true);
    assert.equal(f.document.getElementById('btn-connect').disabled,true);
    assert.match(f.document.querySelector('.cloud-model-loading').textContent,/could not be loaded/);
  }finally{f.dispose();}
});

test('Administrator chat runs before geometry with null context, binds the real model afterward and disposes on exit',async()=>{
 const f=fixture({mode:'admin',locale:'zh-CN'});await f.boot;await flush();
 const send=async()=>{f.document.getElementById('voice-text-input').value='Close model gripper';f.document.getElementById('voice-text-form').dispatchEvent(new f.window.Event('submit',{cancelable:true}));await flush();};
 try{
  assert.equal(f.document.documentElement.lang,'en');
  assert.equal(f.document.getElementById('btn-voice-toggle').disabled,false);
  assert.equal(f.document.getElementById('voice-text-send').disabled,false);
  await send();assert.equal(f.aiCalls.length,1);assert.equal(f.aiCalls[0].body.joints,null);assert.equal(f.aiCalls[0].body.gripper,null);assert.deepEqual(f.aiCalls[0].options,{timeoutMs:35000});
  const preview=f.document.querySelector('#voice-conversation .action-btn');preview.click();assert.match(preview.textContent,/loading/);
  f.resolveModel();await (await f.boot).modelTask;await flush();preview.click();assert.equal(preview.textContent,'Preview applied');
  assert.equal(f.document.getElementById('gripper-input').value,'0');assert.equal(f.document.getElementById('chk-sync').checked,false);
  await send();assert.deepEqual(f.aiCalls[1].body.joints,[0,90,-90,0,0,0]);
  f.dispose();await send();assert.equal(f.aiCalls.length,2);assert.equal(f.document.getElementById('voice-text-send').disabled,true);
 }finally{f.resolveModel();f.dispose();}
});
test('Observer cannot mount authenticated AI even while model loading',async()=>{
 const f=fixture({slowModules:true});await f.boot;await flush();try{
  assert.equal(f.document.getElementById('btn-voice-toggle').disabled,true);
  f.document.getElementById('voice-text-input').value='Hello';f.document.getElementById('voice-text-form').dispatchEvent(new f.window.Event('submit',{cancelable:true}));await flush();assert.equal(f.aiCalls.length,0);
 }finally{f.dispose();}
});

test('startup binds current measured context after geometry and retains out-of-edit numeric feedback',async()=>{
 const joints=[3,-12.21,-75,0,0,0];
 const measurement={deviceId:'fixture',fresh:true,status:'connected',value:{sequence:1,context:{}},sample:{sourceMode:'hardware',sdkConnected:true,jointPositionRad:joints.map(v=>v*Math.PI/180),gripper:{positionRatio:.4}}};
 const f=fixture({mode:'admin',measurement});await f.boot;f.resolveModel();await (await f.boot).modelTask;await flush();try{
  assert.equal(f.document.getElementById('jinput-1').value,'-12.21');assert.equal(f.document.getElementById('slider-j1').disabled,true);
  f.document.getElementById('voice-text-input').value='Describe this pose';f.document.getElementById('voice-text-form').dispatchEvent(new f.window.Event('submit',{cancelable:true}));await flush();
  assert.equal(f.aiCalls[0].body.joints,null);assert.equal(f.aiCalls[0].body.gripper,.4);
 }finally{f.dispose();}
});
