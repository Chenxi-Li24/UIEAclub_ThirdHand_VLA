'use strict';
const { randomUUID } = require('node:crypto');
const { planTransfer } = require('./worker');
const { loadSdkModel,resolveTransfer,positionError,orientationError } = require('./sdk-model');
const {safetyPoseAllowed}=require('./safe-poses');
const MEITUAN_SKILL='meituan_battery_pnp@1';
const WORKSPACE=[[0.15,0.66],[-0.65,0.45],[0.04,0.65]];
const expiry=value => typeof value==='number' && Number.isFinite(value)?value:Date.parse(value);
const sleep=ms => new Promise(resolve => setTimeout(resolve,ms));
function check(value,message) { if (!value) throw new Error(message); }
function ready(state,idle=true) {
  return state.connected && !state.simulated && state.stateFresh && state.ageMs<=500 &&
    (!idle || (state.stateName==='IDLE' && !state.motionActive));
}
function validateMeituanCandidate(candidate) {
  const params=candidate?.payload?.params;
  if (candidate?.skill!==MEITUAN_SKILL || candidate.intent!=='meituan.battery_transfer' ||
      candidate.requiresConfirmation!==true || !params ||
      Object.keys(params).sort().join(',')!=='destination,source' ||
      !['A','B','C','D'].includes(params.source) || !['T0','P1','P2','P3'].includes(params.destination) ||
      (params.destination==='T0' && params.source!=='A')) {
    return {ok:false,reason:'美团参数只接受来源 A/B/C/D 和目标 T0/P1/P2/P3；禁止携带动作'};
  }
  return {ok:true};
}
class MeituanExecutor {
  constructor(options) {
    this.bridge=options.bridge; this.enabled=options.enabled===true;
    this.loadModel=options.loadModel || (() => loadSdkModel(options.modelFiles));
    this.loadPlan=options.loadPlan || (params => resolveTransfer(planTransfer(params),this.loadModel()));
    this.wait=options.wait || sleep; this.pollMs=options.pollMs ?? 40;
    this.feedbackStableMs=options.feedbackStableMs ?? 250;
    this.commandTimeoutMs=options.commandTimeoutMs ?? 45000;
    this.arrivalFeedbackTimeoutMs=options.arrivalFeedbackTimeoutMs ?? 2000;
    this.prepared=new Map(); this.preparing=new Set(); this.active=null; this.stopping=false;
    this.bridge.on('message',message=>{
      if (message.type==='software_stop_complete' ||
          (message.type==='connection' && message.connected===false)) this.stopping=false;
    });
  }
  isActive() { return Boolean(this.active) || this.stopping; }
  async prepare(candidate) {
    const id=candidate?.candidateId;
    try {
      check(this.enabled,'美团真机执行未启用');
      check(!this.isActive() && !this.preparing.has(id),'已有路线执行或正在预览');
      const validation=validateMeituanCandidate(candidate); check(validation.ok,validation.reason);
      check(expiry(candidate.expiresAt)>Date.now(),'候选已过期');
      const state=this.bridge.getRobotState();
      check(ready(state),'3000 未连接、状态不新鲜或机械臂未空闲');
      this.preparing.add(id);
      // Retain at most current candidates, never keep unbounded browser history.
      for (const [key,bound] of this.prepared) if (bound.expiresAt<=Date.now()) this.prepared.delete(key);
      check(this.prepared.size<64,'候选过多，请取消旧候选');
      const model=this.loadModel(); let route=this.loadPlan(candidate.payload.params);
      check(state.flangePositionM && state.flangeEulerRad &&
        model.matches(state.jointsDeg,{position:state.flangePositionM,euler:state.flangeEulerRad}),
        'SDK 模型与实时末端反馈不一致，禁止执行');
      for (const name of ['zero','observe']) {
        const preset=this.bridge.getPreset(name);
        check(preset && model.jointsAllowed(preset),'3000 缺少可用 '+name+' 预设');
        if (name==='observe') check(preset.every((x,i) => Math.abs(x-route.steps.find(s=>s.id==='observe').jointsDeg[i])<0.01),
          '3000 observe 与点位记录不一致');
      }
      for (const step of route.steps) {
        if (step.kind==='joint') {
          check(model.jointsAllowed(step.jointsDeg,step.point),step.point+' 超出六轴限位');
          continue;
        }
        if (step.kind!=='cartesian') continue;
        check(step.id==='transfer_xy','未经示教的笛卡尔步骤');
        check(step.position.every((x,i)=>Number.isFinite(x) && x>=WORKSPACE[i][0] && x<=WORKSPACE[i][1]),
          step.id+' 超出工作空间');
        check(step.position[2]>=step.minBaseZMm/1000,step.id+' 低于146mm搬运下限');
        check(expiry(candidate.expiresAt)>Date.now(),'候选已过期');
        check(ready(this.bridge.getRobotState()),'搬运预览期间机械臂状态未就绪');
        const ik=await this.bridge.previewIk(step.position,step.euler);
        check(ik.ok && safetyPoseAllowed(model,ik.jointsDeg,step),
          step.id+'：'+(ik.reason || '水平搬运目标不可达'));
      }
      route.safetyAdjustments=[];
      check(expiry(candidate.expiresAt)>Date.now() && !this.active,'候选过期或机械臂已被占用');
      const current=this.bridge.getRobotState();
      check(ready(current) && current.jointsDeg.every((x,i)=>Math.abs(x-state.jointsDeg[i])<=1),
        '预览期间机械臂位置已变化，请重新输入');
      this.prepared.set(id,{route,model,origin:[...current.jointsDeg],traceId:candidate.traceId,
        params:JSON.stringify(candidate.payload.params),expiresAt:expiry(candidate.expiresAt)});
      return {ok:true,executionMode:'real',route:route.steps.map(s=>s.id),
        source:route.input.source,destination:route.input.destination,adjustments:route.safetyAdjustments,
        summary:route.safetyAdjustments.map(a=>a.step+'：'+
          (a.liftMm===undefined?'安全高度对齐':('上抬'+a.liftMm.toFixed(1)+'mm'))+
          '，姿态调整'+a.tiltDeg.toFixed(2)+'°').join('；')};
    } catch (error) { return {ok:false,reason:error.message}; }
    finally { this.preparing.delete(id); }
  }
  discard(id) { this.prepared.delete(id); }
  cancel(reason='软件停止') {
    if (!this.active) return false;
    this.stopping=true;
    this.active.stopRequested=true;
    this.bridge.softwareStop();
    this.active.controller.abort(new Error(reason));
    return true;
  }
  async start(request) {
    const {candidate,confirmation,emit=()=>{}}=request;
    let run=null;
    const output=(type,data)=>emit({type,candidateId:candidate?.candidateId,traceId:candidate?.traceId,skill:MEITUAN_SKILL,...data});
    try {
      check(this.enabled && !this.isActive(),'美团执行未启用或已有路线在运行');
      const validation=validateMeituanCandidate(candidate); check(validation.ok,validation.reason);
      check(confirmation?.decision==='confirmed' && confirmation.candidateId===candidate.candidateId &&
        confirmation.traceId===candidate.traceId,'需要整条路线的一次匹配确认');
      const bound=this.prepared.get(candidate.candidateId);
      check(bound && bound.traceId===candidate.traceId && bound.params===JSON.stringify(candidate.payload.params) &&
        bound.expiresAt>Date.now(),'路线预览缺失、已消费或过期，请重新输入');
      this.prepared.delete(candidate.candidateId);
      const model=this.loadModel(),route=this.loadPlan(candidate.payload.params),state=this.bridge.getRobotState();
      check(route.pointsDigest===bound.route.pointsDigest && model.digest===bound.model.digest,
        '标定或 SDK 模型在预览后变化，请重新输入');
      check(ready(state) && state.jointsDeg.every((x,i)=>Math.abs(x-bound.origin[i])<=1),
        '机械臂状态或起始位置已变化，请重新输入');
      run={controller:new AbortController(),candidateId:candidate.candidateId,motionSent:false};
      this.active=run;
      for (let i=0;i<bound.route.steps.length;i++) {
        run.controller.signal.throwIfAborted();
        check(ready(this.bridge.getRobotState()),'机械臂状态未就绪，停止后续步骤');
        const step=bound.route.steps[i];
        output('skill.execution.status',{step:step.id,index:i+1,total:bound.route.steps.length,
          message:'执行 '+(i+1)+'/'+bound.route.steps.length+'：'+step.id});
        if (step.kind==='hold') await this._hold(step.durationMs,run);
        else {
          if (step.kind==='cartesian') {
            const ik=await this.bridge.previewIk(step.position,step.euler);
            check(ik.ok && safetyPoseAllowed(model,ik.jointsDeg,step),
              step.id+'：执行前 IK 检查失败');
          }
          await this._act(step,run);
        }
      }
      const result={success:true,status:'success',message:'完整路线 '+route.input.source+' → '+route.input.destination+
        ' 已按动作反馈执行完成；电池抓稳与放置结果请实机复核。',verification:'actuator_feedback'};
      output('skill.result',result); return result;
    } catch (error) {
      if (run?.motionSent && !run.stopRequested) { this.stopping=true; this.bridge.softwareStop(); }
      const result={success:false,status:'failed',message:error.message};
      output('skill.result',result); return result;
    } finally { if (this.active===run) this.active=null; }
  }
  async _hold(ms,run) {
    // Production holds remain interruptible and monitor fresh feedback continuously.
    const end=Date.now()+ms;
    if (this.wait!==sleep) { await this.wait(ms); run.controller.signal.throwIfAborted(); return; }
    while (Date.now()<end) {
      run.controller.signal.throwIfAborted();
      check(ready(this.bridge.getRobotState()),'保持期间机械臂状态异常');
      await sleep(Math.min(this.pollMs,end-Date.now()));
    }
  }
  async _act(step,run) {
    const state=this.bridge.getRobotState(),requestId=randomUUID();
    // Command 35% unchanged; contact with a battery can settle above that target.
    // This exception is local to the named grasp step, never release/preparation.
    const batteryGrasp=step.kind==='gripper' && step.id==='grasp' && step.position===0.35;
    const openingAccepted=value=>Number.isFinite(value) && (batteryGrasp
      ? value>=0 && value<0.40 : Math.abs(value-step.position)<=0.03);
    const stableMs=batteryGrasp ? Math.max(300,this.feedbackStableMs) : this.feedbackStableMs;
    let command,targetJoints=null;
    if (step.kind==='preset') {
      targetJoints=this.bridge.getPreset(step.name);
      check(targetJoints,'预设缺失：'+step.name);
      if (state.jointsDeg.every((x,i)=>Math.abs(x-targetJoints[i])<=0.1)) return;
      command={cmd:'preset_named',name:step.name,request_id:requestId};
    } else if (step.kind==='gripper') command={cmd:'gripper',position:step.position,request_id:requestId,
      ...(batteryGrasp?{grasp_feedback_upper:0.4}:{})};
    else if (step.kind==='joint') {
      targetJoints=step.jointsDeg;
      if (state.jointsDeg.every((x,i)=>Math.abs(x-targetJoints[i])<=0.1)) return;
      command={cmd:'meituan_joint_point',point:step.point,joints_deg:[...targetJoints],request_id:requestId};
    } else {
      if (step.id==='transfer_xy') check(Number.isFinite(state.flangePositionM?.[2]) &&
        state.flangePositionM[2]>=step.minBaseZMm/1000,'水平搬运起点反馈低于146mm下限');
      const distance=positionError(state.flangePositionM,step.position);
      const angle=orientationError(state.flangeEulerRad,step.euler);
      if (distance<=0.0005 && angle<=0.005) {
        check(!step.safetyReferenceEuler ||
          orientationError(state.flangeEulerRad,step.safetyReferenceEuler)<=5*Math.PI/180+1e-8,
          step.id+'：实际安全姿态超过5°');
        return;
      }
      command={cmd:'move_l',position:step.position,euler:step.euler,request_id:requestId,
        position_tolerance_m:0.005,orientation_tolerance_rad:0.05};
    }
    await new Promise((resolve,reject)=>{
      let completed=false,completedAt=null,stableSince=null,finished=false;
      const end=Date.now()+this.commandTimeoutMs;
      const finish=error=>{
        if (finished) return; finished=true; clearInterval(timer);
        this.bridge.removeListener('message',onMessage);
        run.controller.signal.removeEventListener('abort',onAbort);
        error?reject(error):resolve();
      };
      const onAbort=()=>finish(run.controller.signal.reason || new Error('已取消'));
      const onMessage=message=>{
        if (message.type==='software_stop_complete' || (message.type==='connection' && !message.connected)) {
          finish(new Error('执行被停止或连接中断')); return;
        }
        if (message.request_id!==requestId) return;
        if (message.type==='error') finish(new Error(message.message || '3000 动作失败'));
        if (message.type==='command_complete') {
          if (step.kind==='gripper') {
            if (batteryGrasp) {
              // Formal 3000's reached flag uses exact-opening tolerance. Require
              // correlated completion and measured contact opening instead.
              if (!openingAccepted(message.actual_position)) {
                finish(new Error('夹取反馈未低于40%')); return;
              }
            } else if (message.reached!==true) {
              finish(new Error('夹爪未到目标开度')); return;
            }
          }
          if (!completed) completedAt=Date.now();
          completed=true;
        }
      };
      const timer=setInterval(()=>{
        if (Date.now()>end) return finish(new Error(step.id+' 动作反馈超时'));
        const current=this.bridge.getRobotState();
        // Formal 3000 pauses pose publishing during motion. A stale pose is
        // not a disconnect; wait within the action deadline for matching
        // completion AND fresh, settled IDLE feedback before advancing.
        if (!current.connected || current.simulated) return finish(new Error('机器人连接断开或状态异常'));
        if (step.id==='transfer_xy' && current.stateFresh && current.ageMs<=500 &&
            Number.isFinite(current.flangePositionM?.[2]) &&
            current.flangePositionM[2]<step.minBaseZMm/1000) {
          return finish(new Error('水平搬运反馈低于146mm下限'));
        }
        // Correlation stays busy when actual pose misses the target. Inspect
        // fresh post-completion IDLE feedback even then, solely to report error.
        if (completed && step.kind==='cartesian' && ready(current,false) &&
            current.stateName==='IDLE' && !(current.upstreamMotionActive ?? current.motionActive) &&
            current.completionFeedbackFresh!==false &&
            Array.isArray(current.flangePositionM) && Array.isArray(current.flangeEulerRad) &&
            Date.now()-completedAt>=this.arrivalFeedbackTimeoutMs) {
          const pos=positionError(current.flangePositionM,step.position)*1000;
          const angle=orientationError(current.flangeEulerRad,step.euler);
          if (pos>5 || angle>0.05) {
            return finish(new Error(step.id+' 已收到完成反馈但末端未到位：位置误差 '+pos.toFixed(2)+
              ' mm（上限 5.00 mm），姿态误差 '+angle.toFixed(4)+' rad（上限 0.0500 rad）；未发送下降指令'));
          }
        }
        if (!completed || !ready(current)) { stableSince=null; return; }
        const atTarget=(step.kind==='preset' || step.kind==='joint')
          ? current.jointsDeg.every((x,i)=>Math.abs(x-targetJoints[i])<=1)
          :step.kind==='gripper'?openingAccepted(current.gripperPosition)
          :current.flangePositionM && current.flangeEulerRad &&
            positionError(current.flangePositionM,step.position)<=0.005 &&
            orientationError(current.flangeEulerRad,step.euler)<=0.05 &&
            (!step.safetyReferenceEuler || orientationError(current.flangeEulerRad,step.safetyReferenceEuler)<=5*Math.PI/180+1e-8);
        if (!atTarget) { stableSince=null; return; }
        stableSince ??= Date.now();
        if (Date.now()-stableSince>=stableMs) finish();
      },this.pollMs);
      this.bridge.on('message',onMessage);
      run.controller.signal.addEventListener('abort',onAbort,{once:true});
      if (run.controller.signal.aborted) return onAbort();
      run.motionSent=true;
      if (!this.bridge.send(command)) finish(new Error('3000 拒绝 '+step.id+'，未继续执行'));
    });
  }
}
module.exports={MeituanExecutor,MEITUAN_SKILL,validateMeituanCandidate};
