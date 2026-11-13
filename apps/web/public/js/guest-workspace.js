// Guest preview: model-only UI, no session, WebSocket, device or motion APIs.
const doc=document;
const shell=globalThis.ThirdHandWorkspace.mountWorkspace(doc,window,{canOpenPage:id=>['overview','control'].includes(id),runSystemCheck:async id=>({status:id==='api'?'passed':'skipped',detail:id==='api'?'Public guest workspace is available.':'Sign in to access authenticated device diagnostics.'})});
for(const id of ['vision','calibration','system','assistant'])doc.querySelector(`[data-page="${id}"]`)?.remove();
for(const selector of ['#btn-voice-toggle','#btn-estop-top','#conn-bar','#sec-gripper','#preset-grid','#voice-panel','#workspace-live-status','#tab-tcp','#workspace-nav .nav-bottom button:not(#workspace-nav-toggle)'])doc.querySelector(selector)?.setAttribute('hidden','');
for(const button of doc.querySelectorAll('#page-control button,#page-control input'))button.disabled=true;
for(const selector of ['#sec-sdk','#device-status-entry','#workspace-nav .workspace-live-status'])doc.querySelector(selector)?.setAttribute('hidden','');
for(const id of ['state-badge','hb-label','conn-ip']){const el=doc.getElementById(id);if(el)el.textContent='Guest · Preview only';}
const mode=doc.getElementById('workspace-mode');mode.textContent='Guest mode';
for(const child of doc.querySelector('.topbar-status').children)if(child!==mode)child.style.display='none';
for(const id of ['sec-presets','sec-rt-angles','tab-gripper','language-select']){const el=doc.getElementById(id);if(el)el.style.display='none';}
doc.querySelector('#page-control .workspace-heading p').textContent='Explore the model. Changes here never move the real robot.';
const signIn=doc.createElement('a');signIn.href='/login';signIn.className='action-btn';signIn.textContent='Sign in';doc.querySelector('.topbar-actions').append(signIn);
const send=doc.getElementById('btn-send');send.textContent='Sign in for robot control';send.disabled=true;
const label=doc.getElementById('model-loading-text');
try{
 const {createViewer}=await import('./model-resources.js');
 const {SceneManager,ArmModel}=createViewer({assetBase:'/guest-assets',timeoutMs:120000,onProgress:(bytes,total)=>{label.textContent=total?`Loading model · ${Math.round(bytes/total*100)}%`:'Loading model…';}});
 const scene=new SceneManager(doc.getElementById('three-container')),arm=new ArmModel(scene.scene);
 await arm.loadingPromise;await arm.geometryReady;arm.setJointAngles([0,90,-90,0,0,0]);scene.fitModel(arm.mount);doc.getElementById('model-loading')?.remove();
 const body=doc.getElementById('joint-controls-body');body.replaceChildren();
 arm.jointLimits.forEach(([min,max],i)=>{
  const row=doc.createElement('label');row.className='joint-row';const title=doc.createElement('span');title.textContent=`J${i+1} · Model preview`;
  const value=doc.createElement('output');const slider=doc.createElement('input');slider.type='range';slider.min=min;slider.max=max;slider.step='0.1';slider.value=arm.getJointAngles()[i];slider.setAttribute('aria-label',`J${i+1} preview angle`);
  const update=()=>{const angles=arm.getJointAngles();angles[i]=Number(slider.value);arm.setJointAngles(angles);value.textContent=Number(slider.value).toFixed(1)+'°';};slider.addEventListener('input',update);update();row.append(title,value,slider);body.append(row);
 });
 for(const [id,action] of [['btn-tool-grid',()=>scene.toggleGrid()],['btn-tool-axes',()=>scene.toggleAxes()],['btn-tool-reset',()=>scene.resetView()],['btn-tool-floor',()=>arm.setInstallMode('floor')],['btn-tool-wall',()=>arm.setInstallMode('wall')]]){const button=doc.getElementById(id);button.disabled=false;button.addEventListener('click',action);}
}catch{label.textContent='Model loading failed. Reload to retry.';}
