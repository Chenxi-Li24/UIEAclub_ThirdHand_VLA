'use strict';

class TcpCalibrationWizard{
 constructor({document:doc=document,fetch:fetchImpl=fetch,crypto:cryptoImpl=crypto}={}){this.document=doc;this.fetch=(...args)=>fetchImpl(...args);this.crypto=cryptoImpl;this.state=null;this.pending=null;this.active=null;this.teaching=false;this.teachTimer=null;this.captureHeld=false;}
 el(id){return this.document.getElementById(id);}
 showUnavailable(reason){this.unavailable=true;this.message(reason);this.el('service-warning').textContent=`Calibration unavailable: ${reason}`;this.el('next-step').textContent='Calibration unavailable. Capture and calibration changes are disabled.';this.document.querySelectorAll('main button').forEach(button=>{button.disabled=true;});if(!this.bound)this.el('software-stop').disabled=true;}
 navigationState(){return {loaded:this.state!==null,known:Boolean(this.state?.robot?.connected&&this.state.robot.stateFresh),unavailable:this.unavailable===true,bound:this.bound===true,teachActive:this.teaching===true,teachPending:this.teachPending===true};}
 async json(url,options){const response=await this.fetch(url,options);const payload=await response.json();if(!response.ok)throw new Error(payload.reason||payload.error||`http_${response.status}`);return payload;}
 async init(){const runtime=await this.json('/api/runtime-config');if(!runtime.tcpCalibration?.ready)throw new Error(runtime.tcpCalibration?.reason||'tcp_calibration_unavailable');this.bind();return this.refresh();}
 async refresh(){const state=await this.json('/api/tcp-calibration/sessions/current');this.render(state);return state;}
 stopHeartbeat(){if(this.teachTimer)clearInterval(this.teachTimer);this.teachTimer=null;}
 startPolling(){if(this.pollTimer)return;this.pollTimer=setInterval(async()=>{
  if(this.refreshing)return;this.refreshing=true;
  try{await this.refresh();}catch(error){this.stopHeartbeat();if(this.state)this.render({...this.state,robot:{...this.state.robot,connected:false,stateFresh:false,locked:true}});this.message(error.message);}
  finally{this.refreshing=false;}
 },1000);}
 requestId(){if(typeof this.crypto.randomUUID==='function')return this.crypto.randomUUID();
  if(typeof this.crypto.getRandomValues!=='function')throw new Error('secure_random_unavailable');
  const bytes=this.crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;}
 async mutate(route,extra={},method='POST',validate){
  if(!this.state?.sessionId)throw new Error('session_missing');const localRevision=this.state.revision;await this.refresh();if(this.state.revision!==localRevision)throw new Error('stale_local_revision');
  validate?.();
  const body={sessionId:this.state.sessionId,expectedRevision:localRevision,requestId:this.requestId(),...extra};
  const result=await this.json(route,{method,headers:{'content-type':'application/json'},body:JSON.stringify(body)});await this.refresh();return result;
 }
 bind(){if(this.bound)return;this.bound=true;const on=(id,fn)=>{const node=this.el(id);if(node)node.onclick=()=>fn().catch(error=>this.message(error.message));};
  on('start-session',()=>this.start());on('record-fit',()=>this.record('fit'));
  on('new-session',async()=>{
   if(!this.el('confirm-new-session').checked)throw new Error('Confirm ending this session and entering new measurements. History and the current TCP are retained.');
   await this.mutate('/api/tcp-calibration/sessions/new',{confirm:true});
   this.captureHeld=false;this.stopHeartbeat();this.resetContact();
   for(const id of ['confirm-new-session','probe-centered','pivot-fixed','estop-ready','manual-only',
    'support-ready','confirm-derive','confirm-distance','confirm-axis','confirm-probe-removed','confirm-production',
    'confirm-activate','confirm-rollback'])this.el(id).checked=false;
   this.render(this.state);
   this.message('Previous session archived; current TCP unchanged. Enter new measurements to start.');
  });
  on('delete-fit',async()=>{const id=this.el('fit-sample').value;if(!id)throw new Error('Select a recorded outlier first. No sample is currently selected for deletion.');return this.mutate(`/api/tcp-calibration/samples/${encodeURIComponent(id)}`,{},'DELETE');});
  on('solve',()=>this.mutate('/api/tcp-calibration/solve'));on('record-validation',()=>this.record('validation'));
  on('derive',()=>this.mutate('/api/tcp-calibration/derive'));on('finalize',async()=>{this.pending=await this.mutate('/api/tcp-calibration/finalize');this.render(this.state);});
  on('activate',async()=>{this.active=await this.mutate('/api/tcp-calibration/activate',{candidateId:this.pending.candidateId,expectedActiveId:this.active?.activeId||null,confirm:true});this.render(this.state);});
  on('rollback',async()=>{this.active=await this.mutate('/api/tcp-calibration/rollback',{expectedActiveId:this.active.activeId,confirm:true});this.render(this.state);});
  on('software-stop',()=>this.stop());
  on('teach-start',()=>this.teach('start'));on('teach-hold',()=>this.teach('hold'));
  this.document.querySelectorAll('input[type=checkbox]').forEach(node=>node.onchange=()=>this.render(this.state));
 }
 resetContact(){for(const id of ['contact-ready','pose-stable'])this.el(id).checked=false;}
 assertRecordable(kind){
  const stage=kind==='fit'?'collecting_fit':'collecting_validation';
  const robot=this.state?.robot;
  if(this.state?.stage!==stage||robot?.locked!==false||robot.teachActive||this.teachPending)throw new Error(robot?.reason||'robot_state_locked');
  if(!this.captureHeld)throw new Error('Confirm the current hold first. A stable held pose can be confirmed without re-entering teaching mode.');
  if(!this.el('contact-ready').checked||!this.el('pose-stable').checked)throw new Error('Confirm light probe contact without loading and a stable held pose.');
 }
 async record(kind){
  if(this.recording)return;
  this.assertRecordable(kind);
  this.recording=true;this.render(this.state);
  try{
   await this.mutate(kind==='fit'?'/api/tcp-calibration/samples':'/api/tcp-calibration/verification-samples',{contactConfirmed:true,probeUnloaded:true},'POST',()=>this.assertRecordable(kind));
   this.captureHeld=false;this.resetContact();this.message('Pose saved. Support the arm, enter teaching, change orientation, then hold the next pose.');
  }finally{this.recording=false;this.render(this.state);}
 }
 async stop(){this.stopHeartbeat();const result=await this.json('/api/tcp-calibration/software-stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})});await this.refresh();return result;}
 async teach(action){
  if(this.teachPending)throw new Error('Changing teaching mode; wait for feedback');
  if(action==='hold'&&this.state?.robot?.teachSupported!==true){
   await this.refresh();const robot=this.state?.robot;
   if(!this.el('support-ready').checked||robot?.locked!==false||robot.teachActive)throw new Error(robot?.reason||'Confirm support and a stationary pose');
   this.captureHeld=true;this.resetContact();this.render(this.state);
   this.message('Stationary pose confirmed. No teaching or damping command was sent. Confirm light, unloaded contact again.');return {accepted:true};
  }
  if(action==='start'&&!this.el('support-ready').checked)throw new Error('Confirm that your partner supports the end-effector body and the emergency-stop operator is ready.');
  if(action==='hold'&&!this.teaching&&!this.el('support-ready').checked)throw new Error('Confirm partner support before confirming the hold.');
  if(action==='start')this.captureHeld=false;
  this.resetContact();
  this.teachPending=true;this.render(this.state);this.message(action==='start'?'Requesting zero-damping teaching; wait for server confirmation':'Holding current pose; wait for stationary feedback');
  if(action==='hold')this.stopHeartbeat();
  try{
   const result=await this.json(`/api/tcp-calibration/teach/${action}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})});
   if(result.accepted!==true)throw new Error('Teaching transition not confirmed');
   if(action==='start'&&result.robot?.teachActive!==true)throw new Error('Teaching state unconfirmed. Do not move the arm manually.');
   if(action==='hold')this.captureHeld=true;
   this.render({...this.state,robot:result.robot});
   if(action==='start'){
    this.stopHeartbeat();
    this.teachTimer=setInterval(()=>this.json('/api/tcp-calibration/teach/keepalive',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})}).catch(error=>{this.stopHeartbeat();this.message(error.message);}),5000);
   }
   if(action==='start')this.el('support-ready').checked=false;
   this.message(action==='start'?'Teaching confirmed. Keep supporting the end-effector body and reposition slowly. J5 may drop; do not release support.':'Hold confirmed. Maintain support, verify the pose holds, then gradually reduce force and check light probe contact.');
   return result;
  }finally{this.teachPending=false;this.render(this.state);}
 }
 async start(){if(this.state?.sessionId){this.message('Existing calibration restored. Continue capture without starting again.');return this.state;}const uncertaintyMm=Number(this.el('uncertainty-mm').value);
  if(!Number.isFinite(uncertaintyMm)||uncertaintyMm<=0||uncertaintyMm>10)throw new Error('Enter actual measurement uncertainty greater than 0 and at most 10 mm.');
  const axis=this.el('tool-axis').value.split(',').map(Number);const body={requestId:this.requestId(),operator:this.el('operator').value,
  measurement:{distanceM:(Number(this.el('needle-mm').value)+Number(this.el('distance-mm').value))/1000,uncertaintyM:uncertaintyMm/1000,toolAxisFlange:axis},
  confirmations:{probeCentered:this.el('probe-centered').checked,pivotFixed:this.el('pivot-fixed').checked,estopReady:this.el('estop-ready').checked,manualTeachOnly:this.el('manual-only').checked}};
  const result=await this.json('/api/tcp-calibration/sessions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});await this.refresh();return result;}
 message(text){const hints={
  request_invalid:'Operation does not match the session. Refresh to restore progress; do not start again.',
  stage_invalid:'Continue with the next-step guidance above.',
  duplicate_orientation:'Orientation too similar to an existing sample. Enter teaching again, choose a distinctly different orientation, and contact the same fixed pivot.',
  robot_state_locked:'Operation unavailable. Connect the arm, hold the pose, and wait for fresh stationary feedback.',
  robot_state_not_recordable:'Not recorded. Wait for a stationary pose and retry.',
  pose_not_stable:'Not recorded. Verifying one second of stability. Hold position, then reconfirm the two checks; repositioning is unnecessary.',
  feedback_sequence_not_new:'Not recorded. Wait for a new feedback sequence. Existing samples are retained.',
  feedback_time_not_new:'Not recorded. Feedback predates existing samples; check the service clock. Repositioning will not resolve this.',
  robot_feedback_stale:'Not recorded. Robot feedback expired; waiting for reconnection.',
  robot_teaching:'Teaching remains active. Hold the current pose first.',
  robot_unhealthy:'Robot feedback is unhealthy. Recording is unavailable.',
  robot_frame_or_state_invalid:'Feedback frame or data validation failed. Check the service; existing samples are retained.',
  teach_service_unavailable:'Teaching unavailable. Check connection status above. Do not force the arm.',
  robot_disconnected:'Robot disconnected. Check the main control page; stop manual repositioning.',
  teach_ack_timeout:'No teaching acknowledgment. Do not reposition; check robot state and use the on-site emergency stop if needed.',
  stale_local_revision:'Session progress changed and was refreshed. Check the current step before retrying.',
  session_revision_conflict:'Another operation updated the session. Refresh before retrying.',
 };const node=this.el('message');if(node)node.textContent=hints[text]||text;}
 render(state){if(!state)return;this.state=state;const robot=state.robot||{};this.el('session-status').textContent=`${state.stage} · revision ${state.revision}`;
  this.teaching=robot.teachActive===true;
  if(this.teaching||!robot.connected||!robot.stateFresh||!robot.stationary)this.resetContact();
  if(!robot.connected||!robot.stateFresh)this.captureHeld=false;
  const validation=state.stage==='collecting_validation';
  this.el('record-fit').hidden=validation;
  this.el('record-validation').hidden=!validation;
  this.el('capture-title').textContent=validation?'Capture three additional independent validation poses':'Capture eight distinct fitting orientations';
  this.el('service-warning').hidden=robot.teachSupported===true;
  this.el('service-warning').textContent=robot.connected?'Teaching is unsupported. This page does not change damping. Use existing controls to position the arm, then confirm it is stationary and held. Do not force the arm.':'Waiting for robot connection and capability checks. Existing sessions restore automatically.';
  this.el('teach-hold').textContent=robot.teachSupported===true?'Hold current pose':'Confirm stationary (no mode change)';
  const started=!!state.sessionId;
  this.el('start-session').disabled=started;this.el('start-session').hidden=started;
  this.el('new-session').disabled=!started||robot.locked!==false||this.teaching||this.teachPending
    ||!this.el('confirm-new-session').checked;
  this.el('setup-fields').hidden=started;
  this.el('session-summary').hidden=!started;
  this.el('session-summary').textContent=started?`Restored ${state.operator||'Current operator'}  session. Tip to grasp center:  ${Number((state.measurement?.distanceM||0)*1000).toFixed(1)} mm; uncertainty:  ${Number((state.measurement?.uncertaintyM||0)*1000).toFixed(1)} mm; tool axis:  [${state.measurement?.toolAxisFlange||'Unknown'}]. Do not restart the session.`:'';
  const fitCount=state.fitSamples?.length||0,validationCount=state.validationSamples?.length||0;
  this.el('fit-progress').textContent=`Recorded ${fitCount} / 8 fitting poses`;
  this.el('validation-progress').textContent=`Recorded ${validationCount} / 3 independent validation poses`;
  let next;
  if(robot.connected!==true)next='Waiting for valid robot-service feedback. Check the main control connection if this persists; this page recovers automatically.';
  else if(!robot.stateFresh)next='State expired. Operations paused until reconnection; samples are retained.';
  else if(this.teachPending)next='Changing mode. Wait for server confirmation before repositioning.';
  else if(this.teaching)next='Keep supporting the end effector and lightly contact the same pivot. The operator should click Hold current pose.';
  else if(!started)next='Complete safety checks and actual measurements, then start the calibration session.';
  else if(robot.locked)next=robot.reason==='pose_not_stable'?'Verifying one second of stability. Maintain position.':'Wait for a healthy stationary state before teaching or recording.';
  else if(this.captureHeld&&['collecting_fit','collecting_validation'].includes(state.stage))next='Hold confirmed and pose stable. Verify both checks, then record the pose.';
  else if(state.stage==='collecting_fit')next=fitCount>=8?'Eight poses captured. Solve TCP to continue.':robot.teachSupported===true?'Support → Teach → Change orientation and lightly contact pivot → Hold → Verify contact and stability → Record.':'Position using existing controls → Wait for stationary hold → Confirm contact and stability → Record. This page does not change damping.';
  else if(state.stage==='collecting_validation')next=validationCount>=3?'Enough independent validation samples. Confirm light contact and independence, then complete validation.':'Repeat teaching, positioning and holding to record three additional independent validation poses.';
  else if(state.stage==='ready_to_finalize')next='Validation passed. Verify distance, tool axis and gripper readiness, then save a pending candidate. Activation is separate.';
  else next='Session ended. Review the results.';
  this.el('next-step').textContent=next;
  if(!this.teaching||robot.connected!==true||robot.stateFresh!==true)this.stopHeartbeat();
  if(state.artifacts){this.pending=state.artifacts.pendingId?{candidateId:state.artifacts.pendingId}:null;this.active=state.artifacts.activeId?{activeId:state.artifacts.activeId,previousActiveId:state.artifacts.previousActiveId}:null;}
  this.el('robot-status').textContent=robot.connected?`Connected · ${this.teaching?'Zero-damping teaching':robot.stationary?'Stationary':'Moving'} · ${robot.stateFresh?'Fresh state':'Stale state'}`:'3000 Disconnected';
  this.el('frame-status').textContent=robot.poseFrame==='robot_flange'?'Flange frame verified':'Waiting for frame validation';this.el('frame-status').title=robot.framePolicyId||'policy Unknown';
  this.el('delete-fit').disabled=state.stage!=='collecting_fit'||fitCount===0;
  const unlocked=robot.locked===false&&!this.teaching&&!this.teachPending&&!this.recording;
  const confirmed=this.captureHeld&&this.el('contact-ready').checked&&this.el('pose-stable').checked;
  this.el('record-fit').disabled=!(state.stage==='collecting_fit'&&unlocked&&confirmed);this.el('solve').disabled=!(state.stage==='collecting_fit'&&state.fitSamples?.length>=8&&!this.teaching&&!this.teachPending);
  this.el('teach-start').disabled=!unlocked||robot.teachSupported!==true||!this.el('support-ready').checked||!['collecting_fit','collecting_validation'].includes(state.stage);
  this.el('teach-hold').disabled=this.teachPending||this.recording||robot.connected!==true||robot.stateFresh!==true
    ||(robot.teachSupported!==true&&robot.locked!==false)||(!this.teaching&&!this.el('support-ready').checked)
    ||!['collecting_fit','collecting_validation'].includes(state.stage);
  this.el('record-validation').disabled=!(state.stage==='collecting_validation'&&unlocked&&confirmed);this.el('derive').disabled=!(state.stage==='collecting_validation'&&!this.teaching&&!this.teachPending&&state.validationSamples?.length>=3&&this.el('confirm-derive').checked);
  const ready=state.stage==='ready_to_finalize'&&state.validationReport?.accepted===true;const finalChecks=['confirm-distance','confirm-axis','confirm-probe-removed','confirm-production'].every(id=>this.el(id).checked);
  this.el('finalize').disabled=!(ready&&finalChecks);this.el('activate').disabled=!(this.pending?.candidateId&&this.el('confirm-activate').checked);this.el('rollback').disabled=!(this.active?.previousActiveId&&this.el('confirm-rollback').checked);
  const select=this.el('fit-sample');if(select){const selected=select.value;select.textContent='';for(const sample of state.fitSamples||[]){const option=this.document.createElement('option');option.value=sample.id;option.textContent=sample.id;select.append(option);}if((state.fitSamples||[]).some(sample=>sample.id===selected))select.value=selected;}
  const report=state.solveReport;if(report){const color={green:'Green',yellow:'Yellow',red:'Red'}[report.classification]||report.classification;this.el('diagnostics').textContent=`${color} · rank ${report.rank}\nRMS ${report.rms_residual_m} m · Maximum ${report.maximum_residual_m} m\nWorst sample ${report.worst_sample_id}\nsingular values ${(report.singular_values||[]).join(', ')}`;}else this.el('diagnostics').textContent='Waiting for solve';
  if(report?.sample_ids && (report.sample_ids.length!==fitCount||!report.sample_ids.every(id=>state.fitSamples.some(s=>s.id===id))))this.el('diagnostics').textContent='Samples changed. Results below are outdated. Complete eight poses and solve again.\n'+this.el('diagnostics').textContent;
  this.el('sdk-transform').textContent='T_flange_sdk_tool = [0.17334, 0, 0] m';this.el('probe-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_probe_tip||state.solveReport?.probe_tip_flange_m||null,null,2);this.el('grasp-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_grasp_tcp||null,null,2);
  this.el('pending-status').textContent=this.pending?.candidateId||'Not saved';
 }
}

if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{const wizard=new TcpCalibrationWizard();
 window.ThirdHandCalibrationNavigationState=()=>wizard.navigationState();
 if(new URLSearchParams(window.location.search).get('embedded')==='1')document.documentElement.dataset.embedded='true';
 wizard.init().then(()=>wizard.startPolling()).catch(error=>wizard.showUnavailable(error.message));window.addEventListener('pagehide',()=>wizard.stopHeartbeat());});
