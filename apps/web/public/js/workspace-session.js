/* Cloud identity and model UI. No legacy WebSocket, microphone or SDK bootstrap. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandWorkspaceSession=api;})(globalThis,function(root){
  'use strict';
  const simulationApi=typeof module==='object'&&module.exports?require('./simulation-controller'):root.ThirdHandSimulation;
  const preferencesApi=typeof module==='object'&&module.exports?require('./preferences'):root.ThirdHandPreferences;
  function createWorkspaceSession({view=root,onRevoked=()=>view.location.assign('/login'),initialIdentity=null,timeoutMs=12000}={}){
    let identity=initialIdentity?{...initialIdentity}:null,timer=null,lastActivity=0,closed=false;
    async function request(path,body){
      if(!path.startsWith('/api/v1/'))throw new Error('Invalid API path');
      try{return await preferencesApi.fetchJson(view,path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(identity?.csrfToken?{'X-CSRF-Token':identity.csrfToken}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})},{timeoutMs});}
      catch(error){if(error.status===401&&error.code==='UNAUTHENTICATED'&&!closed){closed=true;onRevoked();}throw error;}
    }
    async function load(){const next=await request('/api/v1/session');if(identity&&(next.userId!==identity.userId||next.sessionId!==identity.sessionId||next.mode!==identity.mode)){onRevoked();throw new Error('Session changed');}identity=next;return {...identity};}
    const activity=()=>{const now=Date.now();if(identity&&now-lastActivity>=60000){lastActivity=now;request('/api/v1/session/activity',{}).catch(()=>{});}};
    const visible=()=>{if(view.document.visibilityState==='visible')load().catch(()=>{});};
    return {request,load,get identity(){return identity?{...identity}:null;},startMonitoring(){
      if(timer!==null)return;timer=view.setInterval(()=>load().catch(()=>{}),5000);
      view.document.addEventListener('pointerdown',activity,{passive:true});view.document.addEventListener('keydown',activity,{passive:true});view.document.addEventListener('visibilitychange',visible);
    },close(){closed=true;if(timer!==null)view.clearInterval(timer);timer=null;view.document.removeEventListener('pointerdown',activity);view.document.removeEventListener('keydown',activity);view.document.removeEventListener('visibilitychange',visible);}};
  }
  function mountWorkspaceEssentials({document:doc,view=root,shell,identity,sessionClient,preferences}){
    const byId=id=>doc.getElementById(id),tr=value=>view.ThirdHandI18n?.translate(value,doc.documentElement.lang)||value;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;};
    const report=message=>{const notice=byId('workspace-notice');notice.hidden=false;notice.textContent=tr(message);};
    const mode=()=>{byId('workspace-mode').textContent=tr(identity.mode==='admin'?'Administrator · model simulation':'Observer · model simulation');};mode();
    for(const selector of ['#btn-connect','#btn-disconnect','#btn-estop-top','#btn-stop-reconnect','#btn-voice-toggle','#sec-xvision button','#sec-dummy button','#sec-gripper button','#tab-tcp'])for(const button of doc.querySelectorAll(selector)){if(button.classList.contains('sec-toggle'))continue;button.disabled=true;button.title=tr('Real robot control is unavailable');}
    if(identity.mode==='observe'){byId('btn-estop-top').hidden=true;const assistant=doc.querySelector('[data-page="assistant"]');if(assistant)assistant.hidden=true;}
    const logout=el('button',{type:'button',id:'workspace-logout',class:'action-btn action-secondary'},'Sign out');
    logout.addEventListener('click',async()=>{logout.disabled=true;try{await sessionClient.request('/api/v1/session/logout',{});preferences?.logout({silent:true});view.location.assign('/login');}catch{logout.disabled=false;report('The service is unavailable. Please try again later.');}});doc.querySelector('.nav-bottom').append(logout);
    shell.setAccountDataProvider({summary:{displayName:identity.displayName||''},loadProfile:async()=>{const profile=await sessionClient.request('/api/v1/me/profile');const email=byId('account-email');if(email){email.readOnly=true;email.title=tr('Email changes require verification.');}return profile;},saveProfile:profile=>sessionClient.request('/api/v1/me/profile',profile)});
    let unsubscribe;
    if(preferences){
      const settings=doc.querySelector('.workspace-settings'),appearance=el('div',{class:'cloud-appearance'}),label=el('label',{for:'workspace-layout-select'},'Interface'),layout=el('select',{id:'workspace-layout-select','aria-label':'Interface'});
      for(const [value,name]of [['workspace','Modern workspace'],['classic','Classic console']]){const option=el('option',{value},name);layout.append(option);}
      const selectLayout=value=>{for(const option of layout.options)option.selected=option.value===value;};
      const theme=el('button',{type:'button',class:'action-btn action-secondary'},'Change theme');
      const save=async(change)=>{layout.disabled=theme.disabled=true;try{await preferences.choose(change);}catch{selectLayout(preferences.current().layoutId);report('Could not save preferences. Please try again.');}finally{layout.disabled=theme.disabled=false;}};
      layout.addEventListener('change',()=>save({layoutId:layout.value}));
      theme.addEventListener('click',()=>{const current=preferences.current();return save(current.layoutId==='classic'?{classicThemeId:current.classicThemeId==='light'?'deepspace':'light'}:{themeId:current.themeId==='light'?'dark':'light'});});
      appearance.append(label,layout,theme);settings.append(appearance);
      byId('language-select').addEventListener('change',event=>preferences.choose({locale:event.target.value}).catch(()=>report('Could not save preferences. Please try again.')));
      const initialLayout=doc.documentElement.dataset.layout||'workspace';
      unsubscribe=preferences.subscribe(value=>{if(value.layoutId!==initialLayout){view.location.reload();return;}preferences.apply(doc,value);selectLayout(value.layoutId);});
    }
    const language=new view.MutationObserver(mode);language.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
    return {dispose(){unsubscribe?.();language.disconnect();}};
  }
  function mountModelWorkspace({document:doc,view=root,shell,arm,scene,identity,sessionClient,preferences,simulationClock}){
    const byId=id=>doc.getElementById(id),tr=value=>view.ThirdHandI18n?.translate(value,doc.documentElement.lang)||value;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;};
    const status=el('p',{id:'simulation-status',role:'status',class:'cloud-simulation-status'},'Model simulation · no robot commands');
    byId('joint-controls-body').before(status);
    const numbers=[],sliders=[],errors=[];
    const report=text=>{status.textContent=tr(text);};
    const simulation=simulationApi.createSimulationController({armModel:arm,...(simulationClock?{clock:simulationClock}:{}),onChange:state=>{
      state.joints.forEach((value,index)=>{if(numbers[index])numbers[index].value=String(Number(value.toFixed(2)));if(sliders[index])sliders[index].value=String(value);});
      if(Number.isFinite(state.gripper)){const number=byId('gripper-input'),slider=byId('gripper-slider');if(number)number.value=String(Number((state.gripper*100).toFixed(2)));if(slider)slider.value=String(state.gripper);}
      status.textContent=tr(state.playing?'Playing model sequence':'Model simulation · no robot commands');
    }});
    const grid=byId('joint-controls-body');grid.replaceChildren();
    arm.jointLimits.forEach(([minimum,maximum],index)=>{
      const row=el('div',{class:'cloud-joint-row'}),label=el('label',{for:`jinput-${index}`},`J${index+1}`),number=el('input',{type:'number',id:`jinput-${index}`,min:minimum,max:maximum,step:.1,'aria-label':`J${index+1} model angle`}),slider=el('input',{type:'range',id:`slider-j${index}`,min:minimum,max:maximum,step:.1,'aria-label':`J${index+1} model angle`}),error=el('span',{id:`jerror-${index}`,role:'alert',class:'cloud-field-error'});
      number.value=slider.value=String(arm.getJointAngles()[index]);numbers.push(number);sliders.push(slider);errors.push(error);row.append(label,number,slider,error);grid.append(row);
      const edit=event=>{const raw=event.target.value,value=Number(raw);if(raw.trim()===''||!Number.isFinite(value)||value<minimum||value>maximum){error.textContent=tr('Enter a valid angle within the joint limits.');return;}error.textContent='';const angles=arm.getJointAngles();angles[index]=value;simulation.setJoints(angles);};
      number.addEventListener('input',edit);slider.addEventListener('input',edit);
    });
    const poses=byId('preset-grid');poses.replaceChildren();
    for(const [name,label]of [['zero','Zero pose'],['ready','Ready pose'],['inspect','Inspection pose']]){
      const button=el('button',{type:'button',class:'preset-btn','data-simulation-preset':name},label);button.addEventListener('click',()=>simulation.playPreset(name).catch(()=>report('Model simulation could not finish.')));poses.append(button);
    }
    const sequence=el('button',{type:'button',id:'play-model-sequence',class:'preset-btn'},'Play model sequence');sequence.addEventListener('click',()=>simulation.playSequence([{joints:[30,70,-110,20,0,0],durationMs:900},{joints:[0,90,-90,0,0,0],durationMs:900}]).catch(()=>report('Model simulation could not finish.')));poses.append(sequence);
    const stop=el('button',{type:'button',id:'stop-model-sequence',class:'action-btn action-secondary'},'Stop model');stop.addEventListener('click',()=>simulation.stop());poses.append(stop);
    const send=byId('btn-send');send.textContent=tr('Apply to model');send.addEventListener('click',()=>{try{if(numbers.some(input=>input.value.trim()===''))throw Error('Empty angle');simulation.setJoints(numbers.map(input=>Number(input.value)));}catch{report('Enter a valid angle within the joint limits.');}});
    const ui={arm,robotConnected:false,robotStateReady:false,syncMode:false,lastRobotState:{stateName:null},selectWorkspaceControl(id){send.hidden=id!=='joints';}};
    shell.bindRuntime({ui,scene});
    byId('workspace-mode').textContent=tr(identity.mode==='admin'?'Administrator · model simulation':'Observer · model simulation');
    for(const selector of ['#btn-connect','#btn-disconnect','#btn-estop-top','#btn-stop-reconnect','#btn-voice-toggle','#sec-dummy button','#sec-gripper button']){
      for(const node of doc.querySelectorAll(selector)){if(node.classList.contains('sec-toggle'))continue;node.disabled=true;node.title=tr('Real robot control is unavailable');}
    }
    if(identity.mode==='observe'){byId('btn-estop-top').hidden=true;const assistant=doc.querySelector('[data-page="assistant"]');if(assistant)assistant.hidden=true;}
    const tcpTab=byId('tab-tcp');if(tcpTab){tcpTab.disabled=true;tcpTab.title=tr('Real robot control is unavailable');}
    for(const [id,callback]of [['btn-tool-grid',()=>scene.toggleGrid()],['btn-tool-axes',()=>scene.toggleAxes()],['btn-tool-reset',()=>scene.resetView()],['btn-tool-floor',()=>arm.setInstallMode('floor')],['btn-tool-wall',()=>arm.setInstallMode('wall')]])byId(id)?.addEventListener('click',callback);
    for(const id of ['gripper-input','gripper-slider'])byId(id)?.addEventListener('input',event=>{const raw=event.target.value,value=Number(raw)/(id==='gripper-input'?100:1);if(raw.trim()!==''&&Number.isFinite(value)&&value>=0&&value<=1){simulation.stop();arm.setGripperPosition(value);byId('gripper-input').value=String(value*100);byId('gripper-slider').value=String(value);}});
    arm.setGripperPosition(1);
    const sync=byId('chk-sync');if(sync){sync.checked=false;sync.disabled=true;sync.title=tr('Live-state mirroring is unavailable');}
    const language=new view.MutationObserver(()=>{byId('workspace-mode').textContent=tr(identity.mode==='admin'?'Administrator · model simulation':'Observer · model simulation');});language.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
    return {simulation,dispose(){simulation.stop();language.disconnect();}};
  }
  return {createWorkspaceSession,mountWorkspaceEssentials,mountModelWorkspace};
});
