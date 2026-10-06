'use strict';

class TcpCalibrationWizard{
 constructor({document:doc=document,fetch:fetchImpl=fetch,crypto:cryptoImpl=crypto}={}){this.document=doc;this.fetch=fetchImpl;this.crypto=cryptoImpl;this.state=null;this.pending=null;this.active=null;}
 el(id){return this.document.getElementById(id);}
 async json(url,options){const response=await this.fetch(url,options);const payload=await response.json();if(!response.ok)throw new Error(payload.error||`http_${response.status}`);return payload;}
 async init(){const runtime=await this.json('/api/runtime-config');if(!runtime.tcpCalibration?.ready)throw new Error(runtime.tcpCalibration?.reason||'tcp_calibration_unavailable');this.bind();return this.refresh();}
 async refresh(){const state=await this.json('/api/tcp-calibration/sessions/current');this.render(state);return state;}
 requestId(){return this.crypto.randomUUID();}
 async mutate(route,extra={},method='POST'){
  if(!this.state?.sessionId)throw new Error('session_missing');const localRevision=this.state.revision;await this.refresh();if(this.state.revision!==localRevision)throw new Error('stale_local_revision');
  const body={sessionId:this.state.sessionId,expectedRevision:localRevision,requestId:this.requestId(),...extra};
  const result=await this.json(route,{method,headers:{'content-type':'application/json'},body:JSON.stringify(body)});if(result.revision!==undefined)this.render(result);return result;
 }
 bind(){if(this.bound)return;this.bound=true;const on=(id,fn)=>{const node=this.el(id);if(node)node.onclick=()=>fn().catch(error=>this.message(error.message));};
  on('start-session',()=>this.start());on('record-fit',()=>this.mutate('/api/tcp-calibration/samples',{contactConfirmed:true,probeUnloaded:true}));
  on('delete-fit',()=>this.mutate(`/api/tcp-calibration/samples/${encodeURIComponent(this.el('fit-sample').value)}`,{},'DELETE'));
  on('solve',()=>this.mutate('/api/tcp-calibration/solve'));on('record-validation',()=>this.mutate('/api/tcp-calibration/verification-samples',{contactConfirmed:true,probeUnloaded:true}));
  on('derive',()=>this.mutate('/api/tcp-calibration/derive'));on('finalize',async()=>{this.pending=await this.mutate('/api/tcp-calibration/finalize');this.render(this.state);});
  on('activate',async()=>{this.active=await this.mutate('/api/tcp-calibration/activate',{candidateId:this.pending.candidateId,expectedActiveId:this.active?.activeId||null,confirm:true});this.render(this.state);});
  on('rollback',async()=>{this.active=await this.mutate('/api/tcp-calibration/rollback',{expectedActiveId:this.active.activeId,confirm:true});this.render(this.state);});
  on('software-stop',()=>this.mutate('/api/tcp-calibration/software-stop'));
  this.document.querySelectorAll('input[type=checkbox]').forEach(node=>node.onchange=()=>this.render(this.state));
 }
 async start(){const axis=this.el('tool-axis').value.split(',').map(Number);const body={requestId:this.requestId(),operator:this.el('operator').value,
  measurement:{distanceM:Number(this.el('distance-mm').value)/1000,uncertaintyM:Number(this.el('uncertainty-mm').value)/1000,toolAxisFlange:axis},
  confirmations:{probeCentered:this.el('probe-centered').checked,pivotFixed:this.el('pivot-fixed').checked,estopReady:this.el('estop-ready').checked,manualTeachOnly:this.el('manual-only').checked}};
  const result=await this.json('/api/tcp-calibration/sessions',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});this.render(result);return result;}
 message(text){const node=this.el('message');if(node)node.textContent=text;}
 render(state){if(!state)return;this.state=state;const robot=state.robot||{};this.el('session-status').textContent=`${state.stage} · revision ${state.revision}`;
  this.el('robot-status').textContent=robot.connected?`已连接 · ${robot.stationary?'静止':'运动中'} · ${robot.stateFresh?'状态新鲜':'状态过期'}`:'3000 未连接';
  this.el('frame-status').textContent=`${robot.poseFrame||'坐标未知'} · ${robot.framePolicyId||'policy 未知'}`;
  const unlocked=robot.locked===false;this.el('record-fit').disabled=!(state.stage==='collecting_fit'&&unlocked);this.el('solve').disabled=!(state.stage==='collecting_fit'&&state.fitSamples?.length>=8);
  this.el('record-validation').disabled=!(state.stage==='collecting_validation'&&unlocked);this.el('derive').disabled=!(state.stage==='collecting_validation'&&state.validationSamples?.length>=3&&this.el('confirm-derive').checked);
  const ready=state.stage==='ready_to_finalize'&&state.validationReport?.accepted===true;const finalChecks=['confirm-distance','confirm-axis','confirm-probe-removed','confirm-production'].every(id=>this.el(id).checked);
  this.el('finalize').disabled=!(ready&&finalChecks);this.el('activate').disabled=!(this.pending?.candidateId&&this.el('confirm-activate').checked);this.el('rollback').disabled=!(this.active?.previousActiveId&&this.el('confirm-rollback').checked);
  const select=this.el('fit-sample');if(select){select.textContent='';for(const sample of state.fitSamples||[]){const option={value:sample.id,textContent:sample.id};if(typeof select.append==='function')select.append(option);}}
  const report=state.solveReport;if(report){const color={green:'绿色',yellow:'黄色',red:'红色'}[report.classification]||report.classification;this.el('diagnostics').textContent=`${color} · rank ${report.rank}\nRMS ${report.rms_residual_m} m · 最大 ${report.maximum_residual_m} m\n最差样本 ${report.worst_sample_id}\nsingular values ${(report.singular_values||[]).join(', ')}`;}
  this.el('sdk-transform').textContent='T_flange_sdk_tool = [0.17334, 0, 0] m';this.el('probe-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_probe_tip||state.solveReport?.probe_tip_flange_m||null,null,2);this.el('grasp-transform').textContent=JSON.stringify(state.derivedTcp?.T_flange_grasp_tcp||null,null,2);
  this.el('pending-status').textContent=this.pending?.candidateId||'尚未保存';
 }
}

if(typeof document!=='undefined')document.addEventListener('DOMContentLoaded',()=>{const wizard=new TcpCalibrationWizard();wizard.init().catch(error=>wizard.message(error.message));});
