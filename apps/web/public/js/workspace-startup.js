/* Lightweight cloud startup. Geometry and video dependencies are independent. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandWorkspaceStartup=api;})(globalThis,function(){
  'use strict';
  async function start({document:doc,view,loadModel}){
    const get=name=>view[name]||globalThis[name],api=get('ThirdHandWorkspaceSession'),tr=text=>view.ThirdHandI18n?.translate(text)||text;
    let bootstrap={};try{bootstrap=JSON.parse(doc.getElementById('workspace-bootstrap')?.textContent||'{}');}catch{}
    const session=api.createWorkspaceSession({view,initialIdentity:bootstrap.identity});
    let identity=bootstrap.identity;
    if(!identity){try{identity=await session.load();}catch(error){if(error.code==='UNAUTHENTICATED')view.location.assign('/login');throw error;}}
    doc.documentElement.dataset.accessMode=identity.mode;
    const preferences=get('ThirdHandPreferences').createPreferenceClient({view,request:(path,body)=>session.request(path,body)});
    await preferences.hydrate(identity,bootstrap.preferences);preferences.apply(doc);
    const tutorialView=get('ThirdHandTutorialAdapter').scopedTutorialView(view,identity.userId);
    const shell=get(bootstrap.preferences?.layoutId==='classic'?'ThirdHandClassicShell':'ThirdHandWorkspace').mountWorkspace(doc,tutorialView,{calibrationEntry:null,canOpenPage:id=>identity.mode==='admin'||id!=='assistant',runSystemCheck:async id=>{
      if(id==='api'){await session.request('/api/v1/session');return {status:'passed',detail:'Authenticated cloud API is reachable.'};}
      if(id==='sdk'||id==='network'){await deviceState?.store.refresh();const state=deviceState?.store.snapshot();const ok=id==='sdk'?state?.status==='connected':state?.value?.gatewayOnline===true;return {status:ok?'passed':'warning',detail:ok?'Verified cloud device feedback is available.':'No fresh device connection is available. Open System for device diagnostics.'};}
      return {status:'unknown',detail:({ai:'The local AI service is not exposed through this cloud gateway.',vision:'Vision service health is not reported by this cloud gateway.',wifi:'Ubuntu Wi-Fi status is not available in cloud telemetry.',tcp:'TCP calibration status is not available in cloud telemetry.'})[id]||'This check is unavailable.'};
    }});
    const essentials=api.mountWorkspaceEssentials({document:doc,view,shell,identity,sessionClient:session,preferences});
    get('ThirdHandAccountSecurity').mountAccountSecurity({document:doc,view,identity,sessionClient:session});
    const navigation=get('ThirdHandWorkspaceNavigation')?.mount({document:doc,view,shell,identity});
    const camera=get('ThirdHandCameraView').mountCameraView({document:doc,view,sessionClient:session});
    const deviceState=get('ThirdHandDeviceState')?.mountDeviceState({document:doc,view,sessionClient:session,shell});
    const liveControls=get('ThirdHandAdminControl').mountAdminControl({document:doc,view,identity,sessionClient:session,stateStore:deviceState?.store});
    shell.attachEssentials?.({preferences});
    session.startMonitoring();doc.getElementById('app').dataset.ready='true';doc.getElementById('workspace-opening')?.remove();
    view.performance?.mark?.('thirdhand:shell-ready');
    const spinner=doc.createElement('p');spinner.className='cloud-model-loading';spinner.setAttribute('role','status');spinner.textContent=tr('Loading model…');doc.getElementById('three-container').append(spinner);
    const initialDisabled=new Map();
    for(const node of doc.querySelectorAll('#joint-controls-body input,#preset-grid button,#btn-send,#gripper-input,#gripper-slider,#workspace-model .view-tools button')){initialDisabled.set(node,node.disabled);node.disabled=true;}
    let active=true,controls,waypoints,modelTimer;
    const modelTask=(async()=>{
      try{
        const resources=await loadModel();if(!active)return;
        const {SceneManager,ArmModel}=resources.createViewer({assetBase:bootstrap.assetBase||'/control-assets'});
        const scene=new SceneManager(doc.getElementById('three-container')),arm=new ArmModel(scene.scene);
        controls=api.mountModelWorkspace({document:doc,view,shell,arm,scene,identity,sessionClient:session,preferences,stateStore:deviceState?.store,modelReady:false});
        waypoints=get('ThirdHandModelWaypoints').mountModelWaypoints({document:doc,view,sessionClient:session,arm,simulation:controls.simulation,ready:false});
        const inputs=Array.from(doc.querySelectorAll('#joint-controls-body input,#preset-grid button,#btn-send,#gripper-input,#gripper-slider,#workspace-model .view-tools button')).map(node=>({node,disabled:initialDisabled.has(node)?initialDisabled.get(node):node.disabled}));
        for(const {node}of inputs)node.disabled=true;
        await arm.loadingPromise;await arm.geometryReady;if(!active)return;
        arm.setJointAngles([0,90,-90,0,0,0]);arm.setGripperPosition(1);controls.setReady(true);scene.fitModel(arm.mount);spinner.remove();doc.getElementById('model-loading')?.remove();
        for(const {node,disabled}of inputs)node.disabled=disabled;
        waypoints.setReady(true);
        view.performance?.mark?.('thirdhand:model-ready');
      }catch{
        if(active){doc.getElementById('model-loading')?.remove();spinner.textContent=tr('The robot model could not be loaded.');const retry=doc.createElement('button');retry.type='button';retry.className='action-btn action-secondary';retry.textContent=tr('Retry model');retry.addEventListener('click',()=>view.location.reload());spinner.append(retry);}
      }finally{view.clearTimeout?.(modelTimer);}
    })();
    modelTimer=view.setTimeout?.(()=>{if(active&&spinner.isConnected){spinner.textContent=tr('The model is taking longer than expected.');const retry=doc.createElement('button');retry.type='button';retry.textContent=tr('Retry model');retry.addEventListener('click',()=>view.location.reload());spinner.append(retry);}},20000);
    view.addEventListener('pagehide',()=>{active=false;view.clearTimeout?.(modelTimer);waypoints?.dispose();camera.dispose();navigation?.dispose();deviceState?.dispose();liveControls?.dispose();controls?.dispose();essentials.dispose();session.close();preferences.dispose();},{once:true});
    shell.installOnboarding(get('ThirdHandOnboarding'));
    void (async()=>{
      let tutorial={state:{status:'unavailable'},entry:null};try{tutorial=await session.request('/api/v1/tutorial');}catch{}
      if(!active)return;
      if(['not_started','in_progress'].includes(tutorial.state.status)&&tutorial.entry){const path=get('ThirdHandTutorialAdapter').resolveEntry({tutorialState:tutorial.state,entry:tutorial.entry,returnTo:'/control'});if(path!=='/control'){view.location.assign(path);return;}}
      let seen=false;try{seen=Boolean(tutorialView.localStorage.getItem('thirdhand.onboarding.v1'));}catch{}
      if(!seen&&tutorial.state.status!=='completed')doc.getElementById('onboarding-start')?.click();
    })();
    return {modelTask,shell};
  }
  return {start};
});
