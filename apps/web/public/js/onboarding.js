/* Optional learning UI. No robot transport, API calls or control-button activation. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandOnboarding=api;})(globalThis,function(){
 'use strict';
 const mounted=new WeakMap(),storageKey='thirdhand.onboarding.v1';
 const tasks=[['status','Read mode and feedback',0],['orbit','Orbit the model',1],['preview','Preview a joint change',2],['vision','Learn the visual grasp flow',3]];
 const steps=[
  {page:'overview',targets:['#workspace-mode','#topbar'],title:'Check your operating mode',body:'Read Simulation, Dry run or Hardware and the SDK feedback. A visible model alone does not mean the robot is connected.'},
  {page:'control',targets:['#workspace-model'],title:'Explore the arm view',body:'Drag the model to orbit and scroll to zoom. Changing the view does not move the robot. Try an orbit to complete this starter task.'},
  {page:'control',targets:['.workspace-tabs'],extras:['#joint-controls-body'],title:'Preview is different from execution',body:'Choose Joints and edit a valid angle to preview the model. Send, presets and demos may move the robot. This guide never presses them for you.'},
  {page:'vision',targets:['#cam-label','#sec-xvision .sec-header'],title:'From a target to a grasp',body:'Wait for a live camera image, select a target, acquire depth and inspect readiness. The existing grasp flow uses calibration and checks its path before execution.'},
  {page:'calibration',targets:['.workspace-calibration-info'],title:'Check calibration provenance',body:'Read the current TCP and its source before a grasp. Use the existing wizard when calibration is needed; this guide never starts collection or changes a result.'},
  {page:'overview',targets:['#btn-estop-top'],title:'Know how to stop and find help',body:'Software Stop can release motor holding force. The independent hardware emergency stop is separate. You do not need to press either to finish this tour. Page help is available on every page.'},
 ];
 const help={
  overview:['Read the overview','Check the operating mode, SDK feedback, camera and TCP status. Unknown or unavailable means the service has not confirmed readiness.'],
  control:['Preview, then decide','Joint edits preview the model. Send, presets and demos may execute motion. TCP targets still need their existing reachability preview; gripper buttons operate the gripper.'],
  vision:['Understand visual grasping','A live camera image and a selected target come first. Depth and calibration turn the target into a robot position; the existing flow then checks the path and executes the grasp. Unavailable controls explain a missing service or prerequisite.'],
  calibration:['Read the tool calibration','The current TCP source and version belong to the existing calibration service. Follow its confirmations when collecting or activating a result. Lock a teaching pose before leaving the wizard.'],
  assistant:['Use voice and text deliberately','Open the microphone only when you want audio capture. AI suggestions still use the existing confirmation flow. Stop or cancel recording before leaving the page.'],
  system:['Use logs to understand status','Communication logs show actual service messages. Appearance settings describe the interface; they do not change robot readiness or calibration.'],
 };
 function mountOnboarding(doc,win,options){
  if(mounted.has(doc))return mounted.get(doc);
  const byId=id=>doc.getElementById(id),tr=value=>win.ThirdHandI18n?.translate(value,doc.documentElement.lang||'en')||value;
  const el=(tag,attrs={},text='')=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;return node;};
  const set=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  let state={version:1,step:0,dismissed:false,tourComplete:false,done:[]};
  try{const saved=JSON.parse(win.localStorage?.getItem(storageKey)||'null');if(saved?.version===1&&Number.isInteger(saved.step)&&saved.step>=0&&saved.step<steps.length&&Array.isArray(saved.done))state={version:1,step:saved.step,dismissed:saved.dismissed===true,tourComplete:saved.tourComplete===true,done:[...new Set(saved.done.filter(id=>tasks.some(task=>task[0]===id)))]};}catch{/* Start with an honest empty checklist if storage is unavailable or corrupt. */}
  const persist=()=>{try{win.localStorage?.setItem(storageKey,JSON.stringify(state));}catch{/* Session-only progress is still usable. */}};
  const context=()=>{try{return options.getContext()||{busy:true};}catch{return {busy:true};}};
  let mode='closed',helpPage='overview',notice='',navigating=false,highlight=null,lastKey='',opener=null,boundScene=null,orbitStart=null;
  const pages=byId('workspace-pages'),overview=byId('page-overview');
  const checklist=el('section',{id:'onboarding-checklist',class:'onboarding-checklist','aria-label':'Getting started'});
  const welcome=el('div',{id:'onboarding-welcome',class:'onboarding-welcome'});
  const welcomeTitle=el('h2',{id:'onboarding-welcome-title'}),welcomeBody=el('p');welcome.append(welcomeTitle,welcomeBody);
  const listTitle=el('div',{class:'onboarding-list-heading'}),listLabel=el('strong'),count=el('span',{'aria-live':'polite'});listTitle.append(listLabel,count);
  const list=el('ol',{class:'onboarding-tasks'}),taskRows=new Map();
  const startButton=el('button',{id:'onboarding-start',type:'button',class:'action-btn action-primary'});
  const laterButton=el('button',{id:'onboarding-later',type:'button',class:'onboarding-text-button'});
  const restartButton=el('button',{id:'onboarding-restart',type:'button',class:'onboarding-text-button'});
  const checklistNote=el('p',{class:'onboarding-status',role:'status'}),actions=el('div',{class:'onboarding-actions'});
  actions.append(startButton,laterButton,restartButton);
  for(const [id,label,index]of tasks){
   const row=el('li',{'data-onboarding-task':id,'data-complete':'false'}),mark=el('span',{class:'onboarding-task-mark','aria-hidden':'true'}),labelNode=el('span'),open=el('button',{type:'button',class:'onboarding-task-open'},'→');
   open.addEventListener('click',()=>{opener=open;startTour(index);});row.append(mark,labelNode,open);list.appendChild(row);taskRows.set(id,{row,mark,labelNode,open,label});
  }
  checklist.append(welcome,listTitle,list,checklistNote,actions);overview.insertBefore(checklist,overview.querySelector('.overview-grid'));
  const panel=el('section',{id:'onboarding-panel',class:'onboarding-panel','aria-label':'Getting started',hidden:''});
  const panelTop=el('div',{class:'onboarding-panel-top'}),stepLabel=el('span',{id:'onboarding-step'}),skip=el('button',{id:'onboarding-skip',type:'button',class:'onboarding-text-button'});panelTop.append(stepLabel,skip);
  const title=el('h2',{id:'onboarding-title',tabindex:'-1'}),body=el('p'),liveStatus=el('p',{class:'onboarding-live-status','data-i18n-skip':''}),panelNotice=el('p',{class:'onboarding-status',role:'status'});
  const panelActions=el('div',{class:'onboarding-actions'}),back=el('button',{id:'onboarding-back',type:'button',class:'onboarding-text-button'}),next=el('button',{id:'onboarding-next',type:'button',class:'action-btn action-primary'}),helpDone=el('button',{id:'onboarding-help-done',type:'button',class:'action-btn action-primary'});
  panelActions.append(back,next,helpDone);panel.append(panelTop,title,body,liveStatus,panelNotice,panelActions);pages.insertBefore(panel,pages.querySelector('.workspace-page'));
  const spotlight=win.ThirdHandOnboardingSpotlight?.mountSpotlight(doc,win,panel,{onTargetVisibilityChange:available=>{if(mode==='tour')next.disabled=context().busy||!available;}});
  const helpButton=el('button',{id:'workspace-guide',type:'button',class:'nav-help','aria-controls':'onboarding-panel'});
  helpButton.hidden=byId('app').dataset.workspaceGroup==='account';
  helpButton.append(el('span',{class:'nav-icon onboarding-help-icon','aria-hidden':'true'},'?'),el('span',{class:'nav-label'},'Getting started'));
  const bottom=doc.querySelector('.nav-bottom');bottom.insertBefore(helpButton,bottom.firstChild);
  for(const [page]of Object.entries(help)){
   const button=el('button',{type:'button',class:'onboarding-page-help','data-page-help':page,'aria-controls':'onboarding-panel'},'Page help');
   button.addEventListener('click',()=>{opener=button;openPageHelp(page);});byId(`page-${page}`).querySelector('.workspace-heading').appendChild(button);
  }
  function clearHighlight(){highlight?.classList.remove('onboarding-highlight');highlight=null;}
  function mark(id){if(!state.done.includes(id)){state.done.push(id);persist();render();}}
  function visibleTarget(selector){const node=doc.querySelector(selector);if(!node||node.closest('[hidden]'))return null;for(let parent=node;parent;parent=parent.parentElement){const style=win.getComputedStyle?.(parent);if(style?.display==='none'||style?.visibility==='hidden')return null;}return node;}
  const tourTarget=()=>steps[state.step].targets.map(visibleTarget).find(Boolean)||null;
  function showHighlight(scroll=false){
   clearHighlight();if(mode!=='tour'||context().busy||notice)return;
   highlight=tourTarget();
   if(highlight){highlight.classList.add('onboarding-highlight');if(scroll&&pages.contains(highlight))highlight.scrollIntoView?.({block:'nearest'});}
   syncSpotlight();
  }
  function syncSpotlight(){const nodes=mode==='tour'?[tourTarget(),...(steps[state.step].extras||[]).map(visibleTarget)].filter(Boolean):[];spotlight?.update(nodes,{visible:mode!=='closed',active:!context().busy,requireTarget:mode==='tour'});}
  function navigate(index){
   if(context().busy){notice='The tour is paused while an operation or teaching state needs attention.';render();return false;}
   let accepted=false;navigating=true;try{accepted=options.go(steps[index].page)!==false;}finally{navigating=false;}
   if(!accepted){notice='The current page cannot be left yet. Finish recording or lock the teaching pose, then try again.';render();return false;}
   notice='';state.step=index;if(index===0)state.tourComplete=false;state.dismissed=true;mode='tour';persist();render();title.focus?.();showHighlight(true);return true;
  }
  function startTour(index=state.step){return navigate(index);}
  function advance(){
   if(mode==='intro'){startTour(state.tourComplete?0:state.step);return;}
   if(mode!=='tour'||context().busy||!tourTarget()||spotlight?.targetVisible===false)return;
   const previous=state.step;
   if(previous===steps.length-1){state.tourComplete=true;state.dismissed=true;persist();close();return;}
   if(navigate(previous+1)){if(previous===0)mark('status');if(previous===3)mark('vision');}
  }
  function close(){
   const restore=panel.contains(doc.activeElement);mode='closed';state.dismissed=true;notice='';persist();clearHighlight();render();if(restore)opener?.focus?.();
  }
  function openPageHelp(page){helpPage=help[page]?page:'overview';mode='help';notice='';clearHighlight();render();pages.scrollTop=0;title.focus?.();}
  function render(){
   const current=context(),busy=current.busy===true,missingTarget=mode==='tour'&&!tourTarget();
   const alertsHeight=byId('workspace-alerts')?.offsetHeight||0;
   const key=JSON.stringify([mode,state,notice,helpPage,current.page,busy,missingTarget,alertsHeight,current.statusText,current.cameraText,doc.documentElement.lang]);
   if(key===lastKey)return;lastKey=key;
   const message=busy?tr('The tour is paused while an operation or teaching state needs attention.'):tr(notice||(missingTarget?'This control is not visible. Return to this lesson when it is available.':''));
   welcome.hidden=state.dismissed||state.tourComplete;
   set(welcomeTitle,tr('Welcome to ThirdHand'));set(welcomeBody,tr('A short tour and four small tasks will help you find your way. No robot action runs automatically.'));
   set(listLabel,tr('Getting started'));set(count,tr('{done} of {total} starter tasks').replace('{done}',state.done.length).replace('{total}',tasks.length));
   for(const [id,item]of taskRows){const done=state.done.includes(id);item.row.dataset.complete=String(done);set(item.mark,done?'✓':'');set(item.labelNode,tr(item.label));item.open.title=tr('Open lesson');item.open.setAttribute('aria-label',`${tr('Open lesson')}: ${tr(item.label)}`);item.open.disabled=busy;}
   set(startButton,tr(state.tourComplete?'Watch the tour again':state.dismissed?'Continue tour':'Start the tour'));startButton.disabled=busy;
   set(laterButton,tr('Later'));laterButton.hidden=state.dismissed||state.tourComplete;
   set(restartButton,tr('Restart tour'));restartButton.hidden=!state.dismissed&&!state.tourComplete;restartButton.disabled=busy;set(checklistNote,message);checklistNote.hidden=!message;
   checklist.hidden=mode!=='closed';panel.hidden=mode==='closed';
   helpButton.setAttribute('aria-expanded',String(mode!=='closed'));helpButton.setAttribute('aria-label',tr('Getting started'));helpButton.title=tr('Getting started');
   back.hidden=mode!=='tour';back.disabled=busy||state.step===0;set(back,tr('Back'));
   next.hidden=mode==='help';next.disabled=busy||missingTarget;helpDone.hidden=mode!=='help';
   set(skip,tr(mode==='tour'?'Skip tour':'Close'));set(helpDone,tr('Got it'));
   if(mode==='tour'){
    const step=steps[state.step];set(stepLabel,tr('Step {step} of {total}').replace('{step}',state.step+1).replace('{total}',steps.length));set(title,tr(step.title));set(body,tr(step.body));set(next,tr(state.step===steps.length-1?'Finish tour':'Next'));
   }else if(mode==='help'){set(stepLabel,tr('Page help'));set(title,tr(help[helpPage][0]));set(body,tr(help[helpPage][1]));}
   else{set(stepLabel,tr('Optional guide'));set(title,tr('Get comfortable with the workspace'));set(body,tr('Learn the interface, try a model preview and return to page help whenever you need it.'));set(next,tr(state.tourComplete?'Watch the tour again':'Continue tour'));}
   set(liveStatus,[current.statusText,current.page==='vision'?current.cameraText:null].filter(Boolean).join(' · '));
   set(panelNotice,message);panelNotice.hidden=!message;
   if(!spotlight)panel.style.top=`${alertsHeight}px`;
   pages.style.setProperty('--onboarding-clearance',spotlight?'0px':`${(panel.offsetHeight||220)+alertsHeight}px`);
   if(busy||mode!=='tour'||notice)clearHighlight();else showHighlight();
   syncSpotlight();
  }
  startButton.addEventListener('click',()=>{opener=startButton;startTour(state.tourComplete?0:state.step);});
  laterButton.addEventListener('click',()=>{state.dismissed=true;persist();render();});
  restartButton.addEventListener('click',()=>{opener=restartButton;state.tourComplete=false;startTour(0);});
  helpButton.addEventListener('click',()=>{opener=helpButton;mode='intro';notice='';clearHighlight();render();pages.scrollTop=0;title.focus?.();});
  next.addEventListener('click',advance);back.addEventListener('click',()=>{if(state.step>0)navigate(state.step-1);});skip.addEventListener('click',close);
  helpDone.addEventListener('click',()=>{if(helpPage==='vision')mark('vision');close();});
  doc.addEventListener('keydown',event=>{if(event.key==='Escape'&&mode!=='closed'){if(panel.contains(event.target)){event.preventDefault();event.stopPropagation();}close();}},true);
  byId('joint-controls-body').addEventListener('input',event=>{
   const input=event.target,match=/^(?:jinput-|slider-j)([0-5])$/.exec(input.id||'');if(!match)return;
   const index=Number(match[1]),requested=Number(input.value),minimum=Number(input.min),maximum=Number(input.max),raw=input.value;
   let before;try{before=options.readJointPreview?.()?.[index];}catch{return;}
   // Native input can run microtasks between capture and target listeners. Read next frame.
   win.requestAnimationFrame(()=>{
    if(raw.trim()===''||!Number.isFinite(before)||Math.abs(before-requested)<1e-5||!Number.isFinite(requested)||!Number.isFinite(minimum)||!Number.isFinite(maximum)||requested<minimum||requested>maximum||byId(`jerror-${index}`)?.textContent)return;
    try{const angles=options.readJointPreview?.();if(Array.isArray(angles)&&Number.isFinite(angles[index])&&Math.abs(angles[index]-requested)<1e-5)mark('preview');}catch{/* Missing model feedback is not completion. */}
   });
  },true);
  function bindScene(scene){
   if(!scene?.controls||!scene.camera||boundScene===scene)return;boundScene=scene;
   const pose=()=>[...scene.camera.position.toArray(),...scene.camera.quaternion.toArray()];
   scene.controls.addEventListener('start',()=>{orbitStart=pose();});
   scene.controls.addEventListener('change',()=>{if(orbitStart&&pose().some((value,index)=>Math.abs(value-orbitStart[index])>1e-5))mark('orbit');});
   scene.controls.addEventListener('end',()=>{orbitStart=null;});
  }
  function routeChanged(){if(!navigating&&mode!=='closed'){mode='closed';notice='';clearHighlight();}render();}
  const languageObserver=new win.MutationObserver(()=>render());languageObserver.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
  const guide={bindScene,refresh:render,routeChanged,openPageHelp};mounted.set(doc,guide);render();return guide;
 }
 return {mountOnboarding};
});
