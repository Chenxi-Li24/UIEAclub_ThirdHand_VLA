/* Optional learning UI. No robot transport, API calls or control-button activation. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandOnboarding=api;})(globalThis,function(){
 'use strict';
 const mounted=new WeakMap(),storageKey='thirdhand.onboarding.v2';
 const tasks=[['status','Understand System Check',0],['ai','Get an AI reply',1],['orbit','Explore the digital twin',2],['preview','Apply a model preview',3],['vision','Understand camera access',4]];
 const steps=[
  {page:'overview',targets:['#system-ready-result','#topbar'],extras:['#system-ready-button'],title:'System Check',body:'Start here to understand readiness. Run the check to review SDK, API, network and TCP calibration status. A check does not connect, enable or move the robot.'},
  {page:'assistant',targets:['#voice-text-form'],title:'Describe an action with AI Agent',body:'Type a question or describe a joint pose. Try: Preview J1 at 20 degrees. Send it yourself and read the reply above the input. The chat stays available while you explore other pages.'},
  {page:'control',targets:['#workspace-model'],title:'See the digital twin',body:'Drag to orbit and scroll or pinch to zoom. This is your model workspace: inspect the pose before deciding what to do next. Moving the view never moves the robot.'},
  {page:'control',targets:['#joint-controls-body'],extras:['#workspace-model'],title:'Preview first. Confirm deliberately.',body:'Compare the proposed joint angles and the model. AI candidates require a separate preview or confirmation action. Follow the permission and validation checks before any physical execution.'},
  {page:'vision',targets:['#cam-label','.camera-feed-container'],title:'Watch the camera',body:'Camera viewing is separate from control permission. Check whether the image is available; a visible picture does not mean the robot is ready to move.'},
  {page:'system',targets:['#page-system'],title:'Keep exploring',body:'Waypoints and history support the three core features. Return to Digital Twin for saved poses, use System for diagnostics, and open Getting started whenever you need this guide again.'},
 ];
 const help={
  overview:['System Check','Review SDK, API, network and TCP calibration results. Unknown, skipped or unavailable is not a passed check. Running checks does not authorize motion.'],
  control:['Digital Twin preview','Orbit the model and inspect joint values. Preview changes and real robot execution are separate actions. Check the current mode and permissions before sending any target.'],
  vision:['Camera access','Viewing a camera does not grant robot control. Missing or stale imagery must not be treated as proof of readiness.'],
  calibration:['TCP calibration','Read the current tool source before using it. Physical sample collection and applying calibration require the existing authorized workflow.'],
  assistant:['AI Agent','Describe one clear action at a time. Review the proposed pose before applying it. AI replies do not grant control permission. Guest text chat is available; guest voice and AI camera analysis are not connected.'],
  system:['Supporting tools','Use diagnostics to understand status. Demo history and real run history are different; real records require an authorized signed-in account.'],
 };
 function mountOnboarding(doc,win,options){
  if(mounted.has(doc))return mounted.get(doc);
  const cloud=!!doc.getElementById('workspace-bootstrap'),guest=doc.getElementById('app')?.dataset.guestDemo==='true';
  const tourSteps=steps.map(step=>({...step}));
  if(guest){
   tourSteps[0].body='System Check introduces SDK, API, network and TCP calibration readiness. In Guest mode, hardware checks are skipped, not passed. You can explore the demo without connecting a robot.';
   tourSteps[3].body='After an AI reply, click Preview in model to apply its candidate. Or move a joint slider here. Both update only the digital twin. Request robot access opens a permission prompt; guests cannot execute real motion.';
   tourSteps[4].body='Guests can watch the real camera as a read-only image refreshed every two seconds. If the source goes offline, the old image is hidden. AI does not see this camera, and viewing does not grant control permission.';
   tourSteps[5].body='Save and recall your own waypoints in Digital Twin. System contains demo history for this visit and CSV export; real run records still require login. Your saved demo poses stay in this browser.';
  }else if(cloud){
   tourSteps[3].body='Sliders, presets and personal waypoints preview the digital twin. Inspect their values and the current permission state. The model alone does not authorize real movement.';
   tourSteps[4].body='Use your camera viewing permission to watch a stream. Video access is separate from SDK connection and physical motion authorization.';
  }
  const byId=id=>doc.getElementById(id),tr=value=>value;
  const el=(tag,attrs={},text='')=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;return node;};
  const set=(node,value)=>{if(node.textContent!==value)node.textContent=value;};
  let state={version:2,step:0,dismissed:false,tourComplete:false,done:[]};
  try{const saved=JSON.parse(win.localStorage?.getItem(storageKey)||'null');if(saved?.version===2&&Number.isInteger(saved.step)&&saved.step>=0&&saved.step<steps.length&&Array.isArray(saved.done))state={version:2,step:saved.step,dismissed:saved.dismissed===true,tourComplete:saved.tourComplete===true,done:[...new Set(saved.done.filter(id=>tasks.some(task=>task[0]===id)))]};}catch{/* Start with an honest empty checklist if storage is unavailable or corrupt. */}
  const persist=()=>{try{win.localStorage?.setItem(storageKey,JSON.stringify(state));}catch{/* Session-only progress is still usable. */}};
  const context=()=>{try{return options.getContext()||{busy:true};}catch{return {busy:true};}};
  let mode='closed',helpPage='overview',notice='',navigating=false,highlight=null,lastKey='',opener=null,boundScene=null,orbitStart=null;
  const pages=options.panelHost||byId('workspace-pages'),overview=options.checklistHost||byId(guest?'page-control':'page-overview');
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
  if(guest)overview.insertBefore(checklist,overview.querySelector('.workspace-heading')?.nextSibling||null);
  const panel=el('section',{id:'onboarding-panel',class:'onboarding-panel','aria-label':'Getting started',hidden:''});
  const panelTop=el('div',{class:'onboarding-panel-top'}),stepLabel=el('span',{id:'onboarding-step'}),skip=el('button',{id:'onboarding-skip',type:'button',class:'onboarding-text-button'});panelTop.append(stepLabel,skip);
  const title=el('h2',{id:'onboarding-title',tabindex:'-1'}),body=el('p'),liveStatus=el('p',{class:'onboarding-live-status','data-i18n-skip':''}),panelNotice=el('p',{class:'onboarding-status',role:'status'});
  const example=el('button',{id:'onboarding-example',type:'button',class:'onboarding-text-button'},'Use example prompt');
  example.addEventListener('click',()=>{const input=byId('voice-text-input');input.value='Preview J1 at 20 degrees. Keep all other joints unchanged.';input.dispatchEvent(new win.Event('input',{bubbles:true}));input.focus();});
  const progress=el('progress',{id:'onboarding-progress',max:String(steps.length),value:'0','aria-label':'Tour progress'});panel.append(progress);
  const panelActions=el('div',{class:'onboarding-actions'}),back=el('button',{id:'onboarding-back',type:'button',class:'onboarding-text-button'}),next=el('button',{id:'onboarding-next',type:'button',class:'action-btn action-primary'}),helpDone=el('button',{id:'onboarding-help-done',type:'button',class:'action-btn action-primary'});
  panelActions.append(example,back,next,helpDone);panel.append(panelTop,title,body,liveStatus,panelNotice,panelActions);const firstPage=pages.querySelector('.workspace-page');pages.insertBefore(panel,firstPage?.parentNode===pages?firstPage:null);
  const spotlight=win.ThirdHandOnboardingSpotlight?.mountSpotlight(doc,win,panel,{onTargetVisibilityChange:available=>{if(mode==='tour')next.disabled=context().busy||!available||!tourTarget();}});
  const helpButton=el('button',{id:'workspace-guide',type:'button',class:'nav-help','aria-controls':'onboarding-panel'});
  helpButton.hidden=byId('app').dataset.workspaceGroup==='account';
  helpButton.append(el('span',{class:'nav-icon onboarding-help-icon','aria-hidden':'true'},'?'),el('span',{class:'nav-label'},'Getting started'));
  const bottom=doc.querySelector('.nav-bottom');bottom.insertBefore(helpButton,bottom.firstChild);
  for(const [page]of Object.entries(help)){
   const button=el('button',{type:'button',class:'onboarding-page-help','data-page-help':page,'aria-controls':'onboarding-panel'},'Page help');
   button.addEventListener('click',()=>{opener=button;openPageHelp(page);});byId(`page-${page}`)?.querySelector('.workspace-heading')?.appendChild(button);
  }
  function clearHighlight(){highlight?.classList.remove('onboarding-highlight');highlight=null;}
  function mark(id){if(!state.done.includes(id)){state.done.push(id);persist();render();}}
  function visibleTarget(selector){const node=doc.querySelector(selector);if(!node||node.closest('[hidden]'))return null;for(let parent=node;parent;parent=parent.parentElement){const style=win.getComputedStyle?.(parent);if(style?.display==='none'||style?.visibility==='hidden')return null;}return node;}
  const tourTarget=()=>(options.resolveTargets?.(tourSteps[state.step].targets)||tourSteps[state.step].targets).map(visibleTarget).find(Boolean)||null;
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
   if(navigate(previous+1)){if(previous===0)mark('status');if(previous===4)mark('vision');}
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
   set(welcomeTitle,tr('Welcome to ThirdHand'));set(welcomeBody,tr('Three core features. One clear journey: check the system, describe an action, and preview it before execution.'));
   set(listLabel,tr('Try the core features'));set(count,tr('{done} of {total} starter tasks').replace('{done}',state.done.length).replace('{total}',tasks.length));
   for(const [id,item]of taskRows){const done=state.done.includes(id);item.row.dataset.complete=String(done);set(item.mark,done?'✓':'');set(item.labelNode,tr(item.label));item.open.title=tr('Open lesson');item.open.setAttribute('aria-label',`${tr('Open lesson')}: ${tr(item.label)}`);item.open.disabled=busy;}
   set(startButton,tr(state.tourComplete?'Watch the tour again':state.dismissed?'Continue tour':'Start the tour'));startButton.disabled=busy;
   set(laterButton,tr('Later'));laterButton.hidden=state.dismissed||state.tourComplete;
   set(restartButton,tr('Restart tour'));restartButton.hidden=!state.dismissed&&!state.tourComplete;restartButton.disabled=busy;set(checklistNote,message);checklistNote.hidden=!message;
   checklist.hidden=mode!=='closed';panel.hidden=mode==='closed';
   helpButton.setAttribute('aria-expanded',String(mode!=='closed'));helpButton.setAttribute('aria-label',tr('Getting started'));helpButton.title=tr('Getting started');
   back.hidden=mode!=='tour';back.disabled=busy||state.step===0;set(back,tr('Back'));
   next.hidden=mode==='help';next.disabled=busy||missingTarget;helpDone.hidden=mode!=='help';
   example.hidden=mode!=='tour'||state.step!==1;example.disabled=busy;progress.hidden=mode!=='tour';progress.value=state.step+1;
   set(skip,tr(mode==='tour'?'Close tour':'Close'));set(helpDone,tr('Got it'));
   if(mode==='tour'){
    const step=tourSteps[state.step];set(stepLabel,tr('Step {step} of {total}').replace('{step}',state.step+1).replace('{total}',steps.length));set(title,tr(step.title));set(body,tr(step.body));set(next,tr(state.step===steps.length-1?'Finish tour':'Next'));
   }else if(mode==='help'){set(stepLabel,tr('Page help'));set(title,tr(help[helpPage][0]));set(body,tr(guest&&['overview','control','vision','system'].includes(helpPage)?tourSteps[{overview:0,control:3,vision:4,system:5}[helpPage]].body:help[helpPage][1]));}
   else{set(stepLabel,tr('Optional guide'));set(title,tr('Start it. Say it. See it.'));set(body,tr('Discover System Check, AI Agent and Digital Twin in six short steps. You can close this guide at any time; no request or motion is triggered automatically.'));set(next,tr(state.tourComplete?'Watch the tour again':'Continue tour'));}
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
  doc.addEventListener('thirdhand:ai-reply',()=>mark('ai'));
  doc.addEventListener('thirdhand:model-preview',()=>mark('preview'));
  function bindScene(scene){
   if(!scene?.controls||!scene.camera||boundScene===scene)return;boundScene=scene;
   const pose=()=>[...scene.camera.position.toArray(),...scene.camera.quaternion.toArray()];
   scene.controls.addEventListener('start',()=>{orbitStart=pose();});
   scene.controls.addEventListener('change',()=>{if(orbitStart&&pose().some((value,index)=>Math.abs(value-orbitStart[index])>1e-5))mark('orbit');});
   scene.controls.addEventListener('end',()=>{orbitStart=null;});
  }
  function routeChanged(){if(!navigating&&mode!=='closed'){mode='closed';notice='';clearHighlight();}render();}
  win.addEventListener('resize',()=>{lastKey='';render();});
  const languageObserver=new win.MutationObserver(()=>render());languageObserver.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
  const guide={bindScene,refresh:render,routeChanged,openPageHelp};mounted.set(doc,guide);render();return guide;
 }
 return {mountOnboarding};
});
