'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {parseHTML}=require('linkedom');
const workspace=require('../../../apps/web/public/js/workspace-session');
const camera=require('../../../apps/web/public/js/camera-view');
const preferences=require('../../../apps/web/public/js/preferences');
const security=require('../../../apps/web/public/js/account-security');
const shellApi=require('../../../apps/web/public/js/workspace-shell');
const startup=require('../../../apps/web/public/js/workspace-startup');
function fixture({slowModules=false,slowProfile=false}={}){
  const {document,window}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  let resolveModel,rejectModel,monitoring=false,fits=0;
  const loading=new Promise((resolve,reject)=>{resolveModel=resolve;rejectModel=reject;});
  const requests=[],events=new Map(),identity={userId:'test',sessionId:'test-session',role:'observer',mode:'observe',csrfToken:'fixture',displayName:'Startup user'};
  const session={load:async()=>identity,request:async(path)=>{requests.push(path);if(path==='/api/v1/me/profile'&&slowProfile)return new Promise(()=>{});return path==='/api/v1/tutorial'?{state:{status:'completed'}}:path==='/api/v1/me/waypoints'?{waypoints:[],limit:100}:path.includes('preferences')?{locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:0}:{};},startMonitoring(){monitoring=true;},close(){}};
  const view={document,location:{hash:'#vision',assign(){}},history:{replaceState(){}},localStorage:{getItem(){return null;},setItem(){}},MutationObserver:window.MutationObserver,addEventListener:(name,fn)=>events.set(name,fn),setInterval(){return 1;},clearInterval(){},ThirdHandAccountSettings:require('../../../apps/web/public/js/account-settings')};
  view.requestAnimationFrame=fn=>fn();view.setTimeout=setTimeout;view.clearTimeout=clearTimeout;
  const data=document.createElement('script');data.id='workspace-bootstrap';data.type='application/json';data.textContent=JSON.stringify({identity,preferences:{locale:'en',themeId:'light',layoutId:'workspace',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:1}});document.head.append(data);
  class Arm{
    constructor(){this.loadingPromise=loading;this.geometryReady=Promise.resolve();this.mount={};this.jointLimits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];this.joints=[0,0,0,0,0,0];}
    getJointAngles(){return this.joints.slice();}setJointAngles(value){this.joints=[...value];}setGripperPosition(){}setInstallMode(){}
  }
  class Scene{constructor(){this.scene={};}fitModel(){fits++;}_onResize(){}toggleGrid(){}toggleAxes(){}resetView(){}}
  Object.assign(view,{
    ThirdHandWorkspaceSession:{...workspace,createWorkspaceSession:()=>session},ThirdHandPreferences:preferences,
    ThirdHandTutorialAdapter:{scopedTutorialView:()=>view},ThirdHandWorkspace:{mountWorkspace(...args){return {...shellApi.mountWorkspace(...args),installOnboarding(){}};}},
    ThirdHandRobotViewer:{createRobotViewer:()=>({SceneManager:Scene,ArmModel:Arm})},ThirdHandAccountSecurity:security,ThirdHandCameraView:camera,
    ThirdHandAdminControl:{mountAdminControl(){return {dispose(){}};}},ThirdHandModelWaypoints:require('../../../apps/web/public/js/model-waypoints'),ThirdHandOnboarding:{}});
  const boot=startup.start({document,view,loadModel:()=>slowModules?new Promise(()=>{}):Promise.resolve({createViewer:()=>({SceneManager:Scene,ArmModel:Arm})})});
  return {document,requests,boot,resolveModel,rejectModel,get monitoring(){return monitoring;},get fits(){return fits;},dispose(){events.get('pagehide')?.();}};
}
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
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
