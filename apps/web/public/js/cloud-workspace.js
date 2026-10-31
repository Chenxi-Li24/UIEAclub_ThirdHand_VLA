import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import './robot-viewer.js';

async function start(){
  const session=globalThis.ThirdHandWorkspaceSession.createWorkspaceSession();
  let identity;
  try{identity=await session.load();}catch{location.assign('/login');return;}
  document.documentElement.dataset.accessMode=identity.mode;
  for(const selector of ['#btn-connect','#btn-disconnect','#btn-estop-top','#btn-stop-reconnect','#btn-voice-toggle']){const button=document.querySelector(selector);if(button)button.disabled=true;}
  const preferences=globalThis.ThirdHandPreferences.createPreferenceClient({view:window,request:(path,body)=>session.request(path,body)});
  await preferences.hydrate(identity);
  preferences.apply(document);
  const tutorialView=globalThis.ThirdHandTutorialAdapter.scopedTutorialView(window,identity.userId);
  const shell=globalThis.ThirdHandWorkspace.mountWorkspace(document,tutorialView,{calibrationEntry:null,canOpenPage:id=>identity.mode==='admin'||id!=='assistant'});
  const {SceneManager,ArmModel}=globalThis.ThirdHandRobotViewer.createRobotViewer({THREE,OrbitControls,STLLoader,ColladaLoader,assetBase:'/control-assets'});
  const scene=new SceneManager(document.getElementById('three-container')),arm=new ArmModel(scene.scene);
  const spinner=document.createElement('p');spinner.className='cloud-model-loading';spinner.textContent='Loading model…';document.getElementById('three-container').append(spinner);
  // Authentication, account and viewing must not wait for the large STL meshes.
  const controls=globalThis.ThirdHandWorkspaceSession.mountModelWorkspace({document,view:window,shell,arm,scene,identity,sessionClient:session,preferences});
  const modelControls=Array.from(document.querySelectorAll('#joint-controls-body input,#preset-grid button,#btn-send,#gripper-input,#gripper-slider,#workspace-model .view-tools button')).map(node=>({node,disabled:node.disabled}));
  for(const {node} of modelControls)node.disabled=true;
  let active=true,liveControls={dispose(){}};
  void Promise.resolve(arm.loadingPromise).then(()=>arm.geometryReady).then(()=>{
    if(!active)return;
    controls.simulation.setJoints([0,90,-90,0,0,0]);arm.setGripperPosition(1);scene.fitModel(arm.mount);spinner.remove();
    for(const {node,disabled} of modelControls)node.disabled=disabled;
    liveControls=globalThis.ThirdHandAdminControl.mountAdminControl({document,view:window,identity,sessionClient:session,arm});
  }).catch(()=>{
    if(active)spinner.textContent=globalThis.ThirdHandI18n?.translate('The robot model could not be loaded.')||'The robot model could not be loaded.';
  });
    globalThis.ThirdHandAccountSecurity.mountAccountSecurity({document,view:window,identity,sessionClient:session});
    const historyLink=document.createElement('a');historyLink.href='/history';historyLink.className='action-btn action-secondary';historyLink.textContent=globalThis.ThirdHandI18n?.translate('Run history')||'Run history';document.querySelector('.nav-bottom').append(historyLink);
    const camera=globalThis.ThirdHandCameraView.mountCameraView({document,view:window,sessionClient:session});
    session.startMonitoring();window.addEventListener('pagehide',()=>{active=false;camera.dispose();liveControls.dispose();controls.dispose();session.close();preferences.dispose();},{once:true});
    shell.installOnboarding(globalThis.ThirdHandOnboarding);
    let tutorial={state:{status:'unavailable'},entry:null};
    try{tutorial=await session.request('/api/v1/tutorial');}catch{/* Keep actual tutorial progress explicitly unavailable. */}
    if(['not_started','in_progress'].includes(tutorial.state.status)&&tutorial.entry){
      const path=globalThis.ThirdHandTutorialAdapter.resolveEntry({tutorialState:tutorial.state,entry:tutorial.entry,returnTo:'/control'});if(path!=='/control'){location.assign(path);return;}
    }
    let seen=false;try{seen=Boolean(tutorialView.localStorage.getItem('thirdhand.onboarding.v1'));}catch{}
    if(!seen&&tutorial.state.status!=='completed')document.getElementById('onboarding-start')?.click();
}
start().catch(()=>{const message=document.createElement('p');message.textContent='The workspace could not be loaded. Please sign in again.';message.className='cloud-start-error';document.body.prepend(message);});
