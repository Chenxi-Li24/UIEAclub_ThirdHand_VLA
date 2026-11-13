// Guest demo: local model previews, browser storage and a read-only camera.
const doc=document;
doc.getElementById('estop-overlay').style.display='none';
const shell=globalThis.ThirdHandWorkspace.mountWorkspace(doc,window,{calibrationEntry:null,runSystemCheck:async id=>({status:'skipped',detail:'Guest preview does not report live hardware status.'})});
const node=(tag,text)=>{const el=doc.createElement(tag);el.textContent=text;return el;};
const permission=doc.createElement('dialog');permission.id='guest-permission';permission.style.cssText='max-width:420px;border:1px solid #eee;border-radius:20px;padding:28px;color:#26313b';
permission.append(node('h2','Control permission required'),node('p','You can explore the demo without signing in. Real robot control requires an authorized account and control permission.'));
const signIn=node('a','Sign in to request access');signIn.href='/login';signIn.className='action-btn action-primary';
const close=node('button','Continue exploring');close.className='action-btn';close.addEventListener('click',()=>permission.close());permission.append(signIn,close);doc.body.append(permission);
const requireControl=()=>{if(!permission.open)permission.showModal();};
const hardwareIds=['btn-connect','btn-disconnect','btn-estop-top','btn-stop-reconnect','btn-send','btn-gripper-send','btn-fixed-tcp-demo','dummy-start','dummy-stop','dummy-confirm-start','btn-active-depth-start','btn-active-depth-stop','btn-grasp-start','btn-grasp-cancel','voice-intent-confirm'];
for(const id of hardwareIds){const button=doc.getElementById(id);if(button){button.disabled=false;button.addEventListener('click',requireControl);}}
for(const selector of ['#workspace-nav .nav-bottom button:not(#workspace-nav-toggle)','#language-select'])doc.querySelector(selector)?.setAttribute('hidden','');
for(const id of ['state-badge','hb-label','conn-ip']){const el=doc.getElementById(id);if(el)el.textContent='Simulation mode';}
const mode=doc.getElementById('workspace-mode');mode.textContent='Guest mode';
for(const child of doc.querySelector('.topbar-status').children)if(child!==mode)child.style.display='none';
for(const id of ['sec-rt-angles','tab-tcp']){const el=doc.getElementById(id);if(el)el.style.display='none';}
doc.querySelector('#page-control .workspace-heading p').textContent='Explore freely. Only real robot actions require control permission.';
const login=node('a','Sign in');login.href='/login';login.className='action-btn';doc.querySelector('.topbar-actions').append(login);
doc.getElementById('btn-voice-toggle').addEventListener('click',()=>shell.go('assistant'));
const calibration=doc.getElementById('page-calibration');calibration.append(node('p','Explore TCP calibration setup. Physical data collection and applying calibration require robot control permission.'));
const calibrate=node('button','Collect calibration sample');calibrate.className='action-btn';calibrate.addEventListener('click',requireControl);calibration.append(calibrate);
const cameraStatus=doc.getElementById('cam-label'),feed=doc.getElementById('xvision-feed');
const cameraRefresh=doc.getElementById('btn-camera-refresh');
cameraRefresh.textContent='Refresh camera';feed.alt='Public camera preview';
cameraStatus.textContent='Read-only camera preview';
doc.querySelector('#page-vision .workspace-heading p').textContent='Watch the public camera preview. Physical actions require control permission.';
for(const el of doc.querySelectorAll('.vision-stream-segment,#detection-list'))el.hidden=true;
doc.getElementById('vision-lock-reason').textContent='Viewing is public. Robot actions require control permission.';
let cameraTimer=null,cameraBusy=false,cameraUrl=null;
const cameraVisible=()=>window.location.hash==='#vision'&&!doc.hidden;
async function refreshCamera(){
 if(cameraBusy||!cameraVisible())return;
 cameraBusy=true;
 try{
  const response=await fetch('/guest-camera/frame',{cache:'no-store',signal:AbortSignal.timeout(7000)});
  if(!response.ok)throw Error('unavailable');
  const blob=await response.blob();if(!cameraVisible())return;
  const next=URL.createObjectURL(blob);feed.src=next;feed.hidden=false;doc.querySelector('.camera-empty').hidden=true;
  if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=next;
  cameraStatus.textContent='Read-only preview · refreshes every 2 seconds';
 }catch{
  feed.hidden=true;doc.querySelector('.camera-empty').hidden=false;feed.removeAttribute('src');if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=null;
  cameraStatus.textContent='Camera unavailable · waiting for the camera source';
 }finally{cameraBusy=false;if(cameraVisible())cameraTimer=setTimeout(refreshCamera,2000);}
}
function cameraVisibility(){clearTimeout(cameraTimer);if(cameraVisible())void refreshCamera();else{feed.removeAttribute('src');if(cameraUrl)URL.revokeObjectURL(cameraUrl);cameraUrl=null;}}
new window.MutationObserver(cameraVisibility).observe(doc.getElementById('page-vision'),{attributes:true,attributeFilter:['hidden']});
window.addEventListener('hashchange',cameraVisibility);doc.addEventListener('visibilitychange',cameraVisibility);
cameraRefresh.addEventListener('click',()=>{clearTimeout(cameraTimer);void refreshCamera();});
if(cameraVisible())void refreshCamera();
const reply=node('p','AI service is not connected to this public demo. You can still explore the model and saved demo poses.');reply.id='guest-ai-status';doc.getElementById('chat-replies').append(reply);
doc.getElementById('voice-text-send').disabled=false;
doc.getElementById('voice-text-form').addEventListener('submit',event=>{event.preventDefault();reply.textContent='AI service is not connected to this public demo. No instruction was sent to a robot.';doc.getElementById('chat-replies').hidden=false;});
for(const id of ['voice-ai-reconnect','voice-record-toggle','voice-mic-toggle']){const button=doc.getElementById(id);if(button){button.disabled=false;button.addEventListener('click',()=>{reply.textContent='Voice and AI services are not configured for this public demo.';doc.getElementById('chat-replies').hidden=false;});}}
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
 const sync=()=>{Array.from(body.querySelectorAll('input')).forEach((input,i)=>{input.value=arm.getJointAngles()[i];input.parentElement.querySelector('output').textContent=Number(input.value).toFixed(1)+'°';});};
 const presets=doc.getElementById('preset-grid');presets.replaceChildren();
 const history=[];const system=doc.getElementById('page-system');const historyLogin=node('a','Sign in to view real run history');historyLogin.href='/login';historyLogin.className='action-btn';system.append(historyLogin);system.append(node('h2','Demo history'),node('p','Preview changes in this visit only. These are not real robot runs.'));const log=node('ul','');system.append(log);
 const record=name=>{history.push({name,joints:arm.getJointAngles(),at:new Date().toISOString()});log.append(node('li',name+' · '+new Date().toLocaleTimeString('en-GB')));};
 const loadPose=(name,joints)=>{arm.setJointAngles(joints);sync();record(name);};
 const poses=[['Home',[0,90,-90,0,0,0]],['Inspection',[20,60,-70,0,20,0]],['Pick preparation',[-20,45,-60,0,15,0]]];
 for(const [name,joints] of poses){const button=node('button',name);button.className='action-btn';button.addEventListener('click',()=>loadPose(name,joints));presets.append(button);}
 const saved=node('section','');saved.append(node('h3','My demo waypoints'),node('p','Saved in this browser only. No account is required.'));
 const input=node('input','');input.placeholder='Waypoint name';input.maxLength=120;input.setAttribute('aria-label','Waypoint name');const save=node('button','Save pose');save.className='action-btn';const list=node('div','');saved.append(input,save,list);presets.after(saved);
 let waypoints=[];try{const stored=JSON.parse(localStorage.getItem('thirdhand.guest.waypoints')||'[]');if(Array.isArray(stored))waypoints=stored.filter(v=>typeof v.name==='string'&&Array.isArray(v.joints)&&v.joints.length===6&&v.joints.every(Number.isFinite)).slice(0,50);}catch{}
 const render=()=>{list.replaceChildren();for(const point of waypoints){const button=node('button',point.name);button.className='action-btn';button.addEventListener('click',()=>loadPose(point.name,point.joints));list.append(button);}};render();
 save.addEventListener('click',()=>{const name=input.value.trim();if(!name)return;waypoints.push({name,joints:arm.getJointAngles()});waypoints=waypoints.slice(-50);try{localStorage.setItem('thirdhand.guest.waypoints',JSON.stringify(waypoints));}catch{}input.value='';render();record('Saved '+name);});
 const gripper=doc.getElementById('gripper-slider'),gripperNumber=doc.getElementById('gripper-input');
 const previewGripper=value=>{arm.setGripperPosition(value);gripper.value=value;gripperNumber.value=Math.round(value*100);};
 gripper.addEventListener('input',()=>previewGripper(Number(gripper.value)));gripperNumber.addEventListener('change',()=>previewGripper(Math.max(0,Math.min(1,Number(gripperNumber.value)/100))));
 for(const [id,value] of [['btn-gripper-open',1],['btn-gripper-close',0]])doc.getElementById(id).addEventListener('click',()=>previewGripper(value));
 const exportButton=node('button','Export demo history');exportButton.className='action-btn';system.append(exportButton);exportButton.addEventListener('click',()=>{const csv='Time,Action,J1,J2,J3,J4,J5,J6\n'+history.map(r=>[r.at,'"'+r.name.replace(/^[=+@\-]/,"' $&").replaceAll('"','""')+'"',...r.joints].join(',')).join('\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));const link=node('a','');link.href=url;link.download='thirdhand-demo-history.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 for(const [id,action] of [['btn-tool-grid',()=>scene.toggleGrid()],['btn-tool-axes',()=>scene.toggleAxes()],['btn-tool-reset',()=>scene.resetView()],['btn-tool-floor',()=>arm.setInstallMode('floor')],['btn-tool-wall',()=>arm.setInstallMode('wall')]]){const button=doc.getElementById(id);button.disabled=false;button.addEventListener('click',action);}
}catch{label.textContent='Model loading failed. Reload to retry.';}
