'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const workspace=require('../../../apps/web/public/js/workspace-session');
const camera=require('../../../apps/web/public/js/camera-view');
const preferences=require('../../../apps/web/public/js/preferences');
const security=require('../../../apps/web/public/js/account-security');
const shellApi=require('../../../apps/web/public/js/workspace-shell');
function fixture(){
  const {document,window}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  let resolveModel,rejectModel,monitoring=false,fits=0;
  const loading=new Promise((resolve,reject)=>{resolveModel=resolve;rejectModel=reject;});
  const requests=[],events=new Map(),identity={userId:'test',sessionId:'test-session',role:'observer',mode:'observe',csrfToken:'fixture'};
  const session={load:async()=>identity,request:async(path)=>{requests.push(path);return path==='/api/v1/tutorial'?{state:{status:'completed'}}:path==='/api/v1/me/waypoints'?{waypoints:[],limit:100}:path.includes('preferences')?{locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:0}:{};},startMonitoring(){monitoring=true;},close(){}};
  const view={document,location:{hash:'#vision',assign(){}},history:{replaceState(){}},localStorage:{getItem(){return null;},setItem(){}},MutationObserver:window.MutationObserver,addEventListener:(name,fn)=>events.set(name,fn),setInterval(){return 1;},clearInterval(){},ThirdHandAccountSettings:require('../../../apps/web/public/js/account-settings')};
  view.requestAnimationFrame=fn=>fn();
  class Arm{
    constructor(){this.loadingPromise=loading;this.geometryReady=Promise.resolve();this.mount={};this.jointLimits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];this.joints=[0,0,0,0,0,0];}
    getJointAngles(){return this.joints.slice();}setJointAngles(value){this.joints=[...value];}setGripperPosition(){}setInstallMode(){}
  }
  class Scene{constructor(){this.scene={};}fitModel(){fits++;}_onResize(){}toggleGrid(){}toggleAxes(){}resetView(){}}
  const context=vm.createContext({document,window:view,location:view.location,THREE:{},OrbitControls(){},STLLoader(){},ColladaLoader(){},
    ThirdHandWorkspaceSession:{...workspace,createWorkspaceSession:()=>session},ThirdHandPreferences:preferences,
    ThirdHandTutorialAdapter:{scopedTutorialView:()=>view},ThirdHandWorkspace:{mountWorkspace(...args){return {...shellApi.mountWorkspace(...args),installOnboarding(){}};}},
    ThirdHandRobotViewer:{createRobotViewer:()=>({SceneManager:Scene,ArmModel:Arm})},ThirdHandAccountSecurity:security,ThirdHandCameraView:camera,
    ThirdHandAdminControl:{mountAdminControl(){return {dispose(){}};}},ThirdHandModelWaypoints:require('../../../apps/web/public/js/model-waypoints'),ThirdHandOnboarding:{}});
  const source=fs.readFileSync('apps/web/public/js/cloud-workspace.js','utf8').replace(/^import .*;\r?$/gm,'').replace('start().catch(()=>{','start().catch(error=>{globalThis.bootError=error;');
  const boot=vm.runInContext(source,context);
  return {document,requests,boot,resolveModel,rejectModel,get error(){return context.bootError;},get monitoring(){return monitoring;},get fits(){return fits;},dispose(){events.get('pagehide')?.();}};
}
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
test('slow model geometry does not block account, camera, or session monitoring; only model controls wait',async()=>{
  const f=fixture();await flush();
  try{
    assert.ifError(f.error);
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
