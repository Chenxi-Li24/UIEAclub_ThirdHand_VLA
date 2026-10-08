'use strict';

class TcpCalibrationWizard{
 constructor({document:doc=document,fetch:fetchImpl=fetch,crypto:cryptoImpl=crypto}={}){this.document=doc;this.fetch=(...args)=>fetchImpl(...args);this.crypto=cryptoImpl;this.state=null;this.pending=null;this.active=null;this.teaching=false;this.teachTimer=null;this.captureHeld=false;}
 el(id){return this.document.getElementById(id);}
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
  on('delete-fit',async()=>{const id=this.el('fit-sample').value;if(!id)throw new Error('请先选择已记录的异常样本；当前没有可删除的样本。');return this.mutate(`/api/tcp-calibration/samples/${encodeURIComponent(id)}`,{},'DELETE');});
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
  if(!this.captureHeld)throw new Error('请先确认本次锁定。已摆好且保持的姿态可以直接确认锁定，无需重新进入拖动。');
  if(!this.el('contact-ready').checked||!this.el('pose-stable').checked)throw new Error('请先确认本次针尖轻触、没有受力，并且锁定后姿态能保持。');
 }
 async record(kind){
  if(this.recording)return;
  this.assertRecordable(kind);
  this.recording=true;this.render(this.state);
  try{
   await this.mutate(kind==='fit'?'/api/tcp-calibration/samples':'/api/tcp-calibration/verification-samples',{contactConfirmed:true,probeUnloaded:true},'POST',()=>this.assertRecordable(kind));
   this.captureHeld=false;this.resetContact();this.message('本次姿态已保存。下一个姿态请重新扶稳、进入拖动、换角度、锁定。');
  }finally{this.recording=false;this.render(this.state);}
 }
 async stop(){this.stopHeartbeat();const result=await this.json('/api/tcp-calibration/software-stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})});await this.refresh();return result;}
 async teach(action){
  if(this.teachPending)throw new Error('正在切换示教模式，请等待反馈');
  if(action==='hold'&&this.state?.robot?.teachSupported!==true){
   await this.refresh();const robot=this.state?.robot;
   if(!this.el('support-ready').checked||robot?.locked!==false||robot.teachActive)throw new Error(robot?.reason||'请确认已扶稳且姿态静止');
   this.captureHeld=true;this.resetContact();this.render(this.state);
   this.message('已确认当前静止姿态；没有发送示教或阻尼切换命令。请再次确认轻触且没有受力。');return {accepted:true};
  }
  if(action==='start'&&!this.el('support-ready').checked)throw new Error('请先确认搭档已托住末端主体，且急停人员就位。');
  if(action==='hold'&&!this.teaching&&!this.el('support-ready').checked)throw new Error('确认当前锁定前，请先勾选搭档已扶稳。');
  if(action==='start')this.captureHeld=false;
  this.resetContact();
  this.teachPending=true;this.render(this.state);this.message(action==='start'?'正在请求 0 阻尼示教，请等待服务端确认':'正在锁定当前姿态，请等待静止反馈');
  if(action==='hold')this.stopHeartbeat();
  try{
   const result=await this.json(`/api/tcp-calibration/teach/${action}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})});
   if(result.accepted!==true)throw new Error('示教切换未确认');
   if(action==='start'&&result.robot?.teachActive!==true)throw new Error('示教状态未确认，请勿拖动');
   if(action==='hold')this.captureHeld=true;
   this.render({...this.state,robot:result.robot});
   if(action==='start'){
    this.stopHeartbeat();
    this.teachTimer=setInterval(()=>this.json('/api/tcp-calibration/teach/keepalive',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({requestId:this.requestId()})}).catch(error=>{this.stopHeartbeat();this.message(error.message);}),5000);
   }
   if(action==='start')this.el('support-ready').checked=false;
   this.message(action==='start'?'示教已确认：搭档持续托住末端主体，缓慢摆位；J5 可能下坠，不要松手。':'锁定反馈已确认。保持支撑，确认姿态能保持，再逐渐减小外力并检查针尖轻触。');
   return result;
  }finally{this.teachPending=false;this.render(this.state);}
 }
 async start(){if(this.state?.sessionId){this.message('已恢复现有标定会话，请继续采集，不需要重复开始。');return this.state;}const uncertaintyMm=Number(this.el('uncertainty-mm').value);
  if(!Number.isFinite(uncertaintyMm)||uncertaintyMm<=0||uncertaintyMm>10)throw new Error('测量不确定度须大于 0 且不超过 10 mm，请按实际测量填写。');
  const axis=this.el('tool-axis').value.split(',').map(Number);const body={requestId:this.requestId(),operator:this.el('operator').value,
  measurement:{distanceM:(Number(this.el('needle-mm').value)+Number(this.el('distance-mm').value))/1000,uncertaintyM:uncertaintyMm/1000,toolAxisFlange:axis},
  confirmations:{probeCentered:this.el('probe-centered').checked,pivotFixed:this.el('pivot-fixed').checked,estopReady:this.el('estop-ready').checked,manualTeachOnly:this.el('manual-only').checked}};
  const result=await this.json('/api/tcp-calibration/sessions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});await this.refresh();return result;}
 message(text){const hints={
  request_invalid:'操作与当前会话不匹配。请刷新页面恢复进度；不要重复开始会话。',
  stage_invalid:'已进入后续步骤，请按顶部的下一步提示继续。',
  duplicate_orientation:'这个角度与已有样本太接近。请重新进入拖动、换一个明显不同的角度，再对准同一固定尖点。',
  robot_state_locked:'暂时不能操作：请先连接机械臂、锁定姿态，并等待静止且状态新鲜。',
  robot_state_not_recordable:'未记录：姿态状态尚未满足要求，请等待静止后重试。',
  pose_not_stable:'未记录：正在确认连续一秒的姿态稳定。请保持当前位置，稳定后重新确认右侧两项即可，无需重新拖动。',
  feedback_sequence_not_new:'未记录：反馈序号没有更新。请等待新反馈；已有样本保留。',
  feedback_time_not_new:'未记录：反馈时间早于已有样本，需核查服务时钟。重新摆位无法解决此问题。',
  robot_feedback_stale:'未记录：机械臂反馈已过期，等待连接恢复。',
  robot_teaching:'仍在拖动示教中，请先锁定当前姿态。',
  robot_unhealthy:'机械臂反馈异常，当前不能记录。',
  robot_frame_or_state_invalid:'反馈坐标或数据校验未通过，请先核查服务；已有样本保留。',
  teach_service_unavailable:'示教服务暂不可用，请查看顶部连接状态；不要强行扳动机械臂。',
  robot_disconnected:'机械臂连接已断开。请在主控制页检查连接；不要继续拖动。',
  teach_ack_timeout:'未收到示教确认，请勿拖动；检查机械臂状态，必要时使用现场急停。',
  stale_local_revision:'会话进度已更新，页面已刷新。请确认当前步骤后重新点击。',
  session_revision_conflict:'另一项操作更新了会话，请刷新进度后重试。',
 };const node=this.el('message');if(node)node.textContent=hints[text]||text;}
 render(state){if(!state)return;this.state=state;const robot=state.robot||{};this.el('session-status').textContent=`${state.stage} · revision ${state.revision}`;
  this.teaching=robot.teachActive===true;
  if(this.teaching||!robot.connected||!robot.stateFresh||!robot.stationary)this.resetContact();
  if(!robot.connected||!robot.stateFresh)this.captureHeld=false;
  const validation=state.stage==='collecting_validation';
  this.el('record-fit').hidden=validation;
  this.el('record-validation').hidden=!validation;
  this.el('capture-title').textContent=validation?'现在采集：另外 3 个独立验证姿态':'现在采集：8 个不同角度的拟合姿态';
  this.el('service-warning').hidden=robot.teachSupported===true;
  this.el('service-warning').textContent=robot.connected?'当前服务没有示教接口。本页不改变阻尼；请使用现有控制方式摆位，待姿态静止保持后点击「确认已静止」。不要强行拖动。':'等待机械臂连接与能力检查，已有会话会自动恢复。';
  this.el('teach-hold').textContent=robot.teachSupported===true?'锁定当前姿态':'确认已静止（不切换模式）';
  const started=!!state.sessionId;
  this.el('start-session').disabled=started;this.el('start-session').hidden=started;
  this.el('setup-fields').hidden=started;
  this.el('session-summary').hidden=!started;
  this.el('session-summary').textContent=started?`已恢复 ${state.operator||'当前操作员'} 的会话。针尖到夹取中心 ${Number((state.measurement?.distanceM||0)*1000).toFixed(1)} mm；不确定度 ${Number((state.measurement?.uncertaintyM||0)*1000).toFixed(1)} mm；工具轴 [${state.measurement?.toolAxisFlange||'未知'}]。无需重复开始。`:'';
  const fitCount=state.fitSamples?.length||0,validationCount=state.validationSamples?.length||0;
  this.el('fit-progress').textContent=`已记录 ${fitCount} / 8 个拟合姿态`;
  this.el('validation-progress').textContent=`已记录 ${validationCount} / 3 个独立验证姿态`;
  let next;
  if(robot.connected!==true)next='正在等待 3000 的有效状态。若持续未连接，请在主控制页确认机械臂已连接；本页会自动恢复。';
  else if(!robot.stateFresh)next='状态已过期，暂停操作，等待连接恢复；已有样本不会丢失。';
  else if(this.teachPending)next='正在切换模式，请等待服务端确认，不要提前拖动。';
  else if(this.teaching)next='搭档继续托住末端，轻触同一个固定尖点；网页操作员点击「锁定当前姿态」。';
  else if(!started)next='完成下方安全检查与实际测量信息，然后点击「开始标定会话」。';
  else if(robot.locked)next=robot.reason==='pose_not_stable'?'正在确认连续一秒的姿态稳定，请保持当前位置。':'等待机械臂静止且状态正常，再进入拖动或记录姿态。';
  else if(this.captureHeld&&['collecting_fit','collecting_validation'].includes(state.stage))next='本次锁定已确认，姿态稳定。核对右侧两项后点击「记录当前姿态」。';
  else if(state.stage==='collecting_fit')next=fitCount>=8?'已采满 8 个姿态，可以点击「求解 TCP」。':robot.teachSupported===true?'搭档扶稳 → 进入拖动 → 换角度轻触固定尖点 → 锁定 → 确认轻触和稳定 → 记录。':'用现有控制方式摆位，等待静止保持 → 确认已静止 → 确认轻触和稳定 → 记录；本页不会切换阻尼。';
  else if(state.stage==='collecting_validation')next=validationCount>=3?'独立验证样本已够，请确认轻触与独立性，然后点击「完成验证并换算」。':'继续用进入拖动、摆位、锁定的流程，记录另外 3 个独立验证姿态。';
  else if(state.stage==='ready_to_finalize')next='验证通过。核对距离、工具轴和夹爪恢复状态，再保存 pending 候选；不会自动激活。';
  else next='当前会话已结束，请核对结果。';
  this.el('next-step').textContent=next;
  if(!this.teaching||robot.connected!==true||robot.stateFresh!==true)this.stopHeartbeat();
  if(state.artifacts){this.pending=state.artifacts.pendingId?{candidateId:state.artifacts.pendingId}:null;this.active=state.artifacts.activeId?{activeId:state.artifacts.activeId,previousActiveId:state.artifacts.previousActiveId}:null;}
  this.el('robot-status').textContent=robot.connected?`已连接 · ${this.teaching?'0 阻尼示教中':robot.stationary?'静止':'运动中'} · ${robot.stateFresh?'状态新鲜':'状态过期'}`:'3000 未连接';
  this.el('frame-status').textContent=robot.poseFrame==='robot_flange'?'法兰坐标已校验':'等待坐标校验';this.el('frame-status').title=robot.framePolicyId||'policy 未知';
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
  const report=state.solveReport;if(report){const color={green:'绿色',yellow:'黄色',red:'红色'}[report.classification]||report.classification;this.el('diagnostics').textContent=`${color} · rank ${report.rank}\nRMS ${report.rms_residual_m} m · 最大 ${report.maximum_residual_m} m\n最差样本 ${report.worst_sample_id}\nsingular values ${(report.singular_values||[]).join(', ')}`;}
  if(report?.sample_ids && (report.sample_ids.length!==fitCount||!report.sample_ids.every(id=>state.fitSamples.some(s=>s.id===id))))this.el('diagnostics').textContent='样本已变更，下面是旧结果；补齐 8 个姿态并重新求解。\n'+this.el('diagnostics').textContent;
  this.el('sdk-transform').textContent='T_flange_sdk_tool = [0.17334, 0, 0] m';this.el('probe-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_probe_tip||state.solveReport?.probe_tip_flange_m||null,null,2);this.el('grasp-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_grasp_tcp||null,null,2);
  this.el('pending-status').textContent=this.pending?.candidateId||'尚未保存';
 }
}

if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{const wizard=new TcpCalibrationWizard();wizard.init().then(()=>wizard.startPolling()).catch(error=>wizard.message(error.message));window.addEventListener('pagehide',()=>wizard.stopHeartbeat());});
