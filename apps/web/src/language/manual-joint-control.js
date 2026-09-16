'use strict';

const { randomUUID } = require('crypto');

const MANUAL_SKILL = 'manual_joint_control@1';
const PICK_SKILL = 'pick_and_place_bottle@1';
const ALLOWED_ACTIONS = new Set([
  'joint.set',
  'joint.step',
  'joint.multi',
  'gripper.open',
  'gripper.close',
  'robot.status',
  'robot.home',
  'safety.stop.request',
]);

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parseExpiry(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeMultiJointMoves(moves) {
  if (!Array.isArray(moves) || moves.length < 2 || moves.length > 6) {
    return { ok: false, reason: '多轴指令必须包含 2–6 个关节' };
  }
  const seen = new Set();
  const normalized = [];
  for (const move of moves) {
    if (!move || typeof move !== 'object' || Array.isArray(move)) {
      return { ok: false, reason: '多轴关节项必须是对象' };
    }
    const keys = Object.keys(move).sort().join(',');
    const field = keys === 'deltaDeg,joint' ? 'deltaDeg'
      : keys === 'joint,targetDeg' ? 'targetDeg' : null;
    if (!field || !Number.isInteger(move.joint) || move.joint < 1 || move.joint > 6 ||
        !Number.isFinite(move[field]) || (field === 'deltaDeg' && move.deltaDeg === 0)) {
      return { ok: false, reason: '每个关节必须给出有效的 joint 和 deltaDeg 或 targetDeg' };
    }
    if (seen.has(move.joint)) {
      return { ok: false, reason: `J${move.joint} 在同一多轴指令中重复` };
    }
    seen.add(move.joint);
    normalized.push({ joint: move.joint, [field]: move[field] });
  }
  return { ok: true, moves: normalized };
}

function validateCandidate(candidate, nowMs) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return { ok: false, reason: 'candidate 必须是对象' };
  }
  for (const field of ['candidateId', 'traceId', 'sourceText', 'skill']) {
    if (typeof candidate[field] !== 'string' || !candidate[field].trim()) {
      return { ok: false, reason: `${field} 必须是非空字符串` };
    }
  }
  const expiresAtMs = parseExpiry(candidate.expiresAt);
  if (expiresAtMs === null) return { ok: false, reason: 'expiresAt 无效' };
  if (expiresAtMs <= nowMs) return { ok: false, reason: '候选已过期' };
  if (expiresAtMs - nowMs > 120_000) {
    return { ok: false, reason: '候选有效期不得超过 120 秒' };
  }
  if (candidate.skill === PICK_SKILL) {
    if (candidate.requiresConfirmation !== true) {
      return { ok: false, reason: 'pick_and_place_bottle@1 必须显式确认' };
    }
    return { ok: true, expiresAtMs, params: null, externalSkill: true };
  }
  if (candidate.skill !== MANUAL_SKILL) {
    return { ok: false, reason: `不支持的 Skill: ${candidate.skill}` };
  }
  const params = candidate.payload?.params;
  if (!params || typeof params !== 'object' || Array.isArray(params)) {
    return { ok: false, reason: 'payload.params 必须是对象' };
  }
  if (!ALLOWED_ACTIONS.has(params.action)) {
    return { ok: false, reason: `不支持的 action: ${String(params.action)}` };
  }
  const stop = params.action === 'safety.stop.request';
  if (stop) {
    if (candidate.requiresConfirmation !== false) {
      return { ok: false, reason: 'software stop 必须标记 requiresConfirmation:false' };
    }
  } else if (candidate.requiresConfirmation !== true) {
    return { ok: false, reason: '动作候选必须标记 requiresConfirmation:true' };
  }
  if (params.action === 'joint.set' || params.action === 'joint.step') {
    if (!Number.isInteger(params.joint) || params.joint < 1 || params.joint > 6) {
      return { ok: false, reason: 'joint 必须是 1 到 6 的整数' };
    }
    const value = params.action === 'joint.set'
      ? finiteNumber(params.targetDeg)
      : finiteNumber(params.deltaDeg);
    if (value === null) {
      return { ok: false, reason: params.action === 'joint.set' ? 'targetDeg 无效' : 'deltaDeg 无效' };
    }
  }
  if (params.action === 'joint.multi') {
    if (candidate.intent !== 'joint.multi' ||
        Object.keys(params).sort().join(',') !== 'action,moves') {
      return { ok: false, reason: '多轴 intent 或参数结构无效' };
    }
    const normalized = normalizeMultiJointMoves(params.moves);
    if (!normalized.ok) return normalized;
    return {
      ok: true, expiresAtMs,
      params: { action: 'joint.multi', moves: normalized.moves },
      externalSkill: false,
    };
  }
  return { ok: true, expiresAtMs, params: clone(params), externalSkill: false };
}

class ManualJointOrchestrator {
  constructor(options = {}) {
    this.enabled = options.enabled === true;
    this.getRobotState = options.getRobotState || (() => ({}));
    this.sendRobot = options.sendRobot || (() => false);
    this.softwareStop = options.softwareStop || (() => false);
    this.moveTimeFor = options.moveTimeFor || (() => 0.5);
    this.getHomeTarget = options.getHomeTarget || (() => null);
    this.onMessage = options.onMessage || (() => {});
    this.now = options.now || Date.now;
    this.makeRequestId = options.makeRequestId || randomUUID;
    this.schedule = options.schedule || setTimeout;
    this.cancelSchedule = options.cancelSchedule || clearTimeout;
    this.jointLimitsDeg = options.jointLimitsDeg || [];
    const configuredMaxDeltaDeg = Number(options.maxDeltaDeg);
    this.maxDeltaDeg = Number.isFinite(configuredMaxDeltaDeg) && configuredMaxDeltaDeg > 0
      ? configuredMaxDeltaDeg
      : null;
    this.speedScale = Number(options.speedScale ?? 0.05);
    this.stateMaxAgeMs = Number(options.stateMaxAgeMs ?? 500);
    this.jointToleranceDeg = Number(options.jointToleranceDeg ?? 1);
    this.gripperOpenTarget = Number(options.gripperOpenTarget ?? 1);
    this.gripperCloseTarget = Number(options.gripperCloseTarget ?? 0);
    this.maxJointTimeoutMs = Number(options.maxJointTimeoutMs ?? 10_000);
    this.maxMultiTimeoutMs = Number(options.maxMultiTimeoutMs ?? 35_000);
    this.maxHomeTimeoutMs = Number(options.maxHomeTimeoutMs ?? 30_000);
    this.gripperTimeoutMs = Number(options.gripperTimeoutMs ?? 5_000);
    this.skillExecutors = options.skillExecutors || null;
    this.sessions = new Map();
    this.consumed = new Map();
    this.active = null;
  }

  runtimeConfig() {
    return {
      enabled: this.enabled,
      skill: MANUAL_SKILL,
      candidateTtlMs: 120_000,
      stateMaxAgeMs: this.stateMaxAgeMs,
      maxDeltaDeg: this.maxDeltaDeg,
      speedScale: this.speedScale,
      jointToleranceDeg: this.jointToleranceDeg,
      gripper: {
        openTarget: this.gripperOpenTarget,
        closeTarget: this.gripperCloseTarget,
      },
      externalSkills: this.skillExecutors?.availableSkills?.() || [],
    };
  }

  register(session, candidate) {
    this._prune();
    const checked = validateCandidate(candidate, this.now());
    if (!checked.ok) {
      return this._send(session, 'skill.candidate.rejected', {
        candidateId: candidate?.candidateId || null,
        traceId: candidate?.traceId || null,
        reason: checked.reason,
      });
    }
    if (checked.externalSkill) {
      const externalChecked = this.skillExecutors?.validate?.(candidate.skill, candidate) || {
        ok: false,
        reason: `${candidate.skill} contract validator 尚未配置`,
      };
      if (!externalChecked.ok) {
        return this._send(session, 'skill.candidate.rejected', {
          candidateId: candidate.candidateId,
          traceId: candidate.traceId,
          reason: externalChecked.reason,
        });
      }
    }
    if (this.consumed.has(candidate.candidateId)) {
      return this._send(session, 'skill.candidate.rejected', {
        candidateId: candidate.candidateId,
        traceId: candidate.traceId,
        reason: '候选已消费，禁止重放',
      });
    }
    if (checked.params?.action === 'safety.stop.request') {
      this.consumed.set(candidate.candidateId, checked.expiresAtMs);
      return this._executeStop(session, candidate);
    }
    let pending = this.sessions.get(session);
    if (!pending) {
      pending = new Map();
      this.sessions.set(session, pending);
    }
    pending.clear();
    pending.set(candidate.candidateId, {
      candidate: clone(candidate),
      expiresAtMs: checked.expiresAtMs,
      params: checked.params,
      externalSkill: checked.externalSkill,
    });
    return this._send(session, 'skill.candidate.registered', {
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      expiresAt: candidate.expiresAt,
    });
  }

  decide(session, decision) {
    this._prune();
    const candidateId = decision?.candidateId;
    const traceId = decision?.traceId;
    const value = decision?.decision;
    if (!candidateId || !traceId || !['approve', 'reject'].includes(value)) {
      return this._send(session, 'skill.result', {
        success: false,
        status: 'rejected',
        candidateId: candidateId || null,
        traceId: traceId || null,
        message: 'confirmation.decision 格式无效',
      });
    }
    const pending = this.sessions.get(session);
    const registered = pending?.get(candidateId);
    if (!registered || registered.candidate.traceId !== traceId) {
      return this._send(session, 'skill.result', {
        success: false,
        status: 'rejected',
        candidateId,
        traceId,
        message: '候选不存在、已过期、trace 不匹配或已经消费',
      });
    }
    pending.delete(candidateId);
    this.consumed.set(candidateId, registered.expiresAtMs);
    if (value === 'reject') {
      return this._send(session, 'skill.result', {
        success: false,
        status: 'rejected',
        candidateId,
        traceId,
        message: '用户已取消，未发送任何硬件命令',
      });
    }
    if (registered.externalSkill) return this._executeExternal(session, registered.candidate);
    return this._execute(session, registered.candidate, registered.params);
  }

  _executeExternal(session, candidate) {
    const confirmation = {
      decision: 'confirmed',
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      decidedAt: this.now(),
    };
    const dispatched = this.skillExecutors?.dispatch?.(candidate.skill, {
      candidate,
      confirmation,
      emit: message => this.onMessage(session, message),
    }) || { accepted: false, reason: `${candidate.skill} adapter 尚未注册` };
    if (!dispatched.accepted) return this._blocked(session, candidate, dispatched.reason);
    this._send(session, 'skill.handoff.accepted', {
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      skill: candidate.skill,
      message: '复杂 Skill 已交给已注册 adapter；Language 未生成任何机械臂动作',
    });
    return true;
  }

  disconnect(session) {
    this.sessions.delete(session);
    if (this.active?.session === session) {
      this.softwareStop();
      this._finish(false, 'failed', '控制页面断开，已请求软件停止；执行结果不确定');
    }
  }

  handleBridgeEvent(message) {
    const active = this.active;
    if (!active || !message || typeof message !== 'object') return false;
    if (message.type === 'connection' && message.connected === false) {
      this._finish(false, 'failed', message.error || message.reason || 'Startouch SDK 连接中断，执行结果不确定');
      return true;
    }
    const requestId = message.request_id || message.requestId;
    if (message.type === 'software_stop_complete' && active.kind === 'stop') {
      this._finish(true, 'success', '软件停止完成，SDK 已清理并请求电机失能');
      return true;
    }
    if (message.type === 'software_stop_timeout' && active.kind === 'stop') {
      this._finish(false, 'failed', message.message || '软件停止超时，失能状态不确定');
      return true;
    }
    if (requestId && requestId !== active.requestId) return false;
    if (message.type === 'error') {
      this._finish(false, 'failed', message.message || '硬件命令失败');
      return true;
    }
    if (message.type === 'command_complete') {
      active.completeReceived = true;
      if (active.kind === 'gripper') {
        if (message.reached === true) {
          this._finish(true, 'success', `${active.label}完成，夹爪反馈 reached:true`);
        } else {
          this._finish(false, 'failed', `${active.label}未达到目标，夹爪反馈 reached:false`);
        }
      } else if (active.kind === 'joint' || active.kind === 'multi' || active.kind === 'home') {
        active.completedAtMs = this.now();
      }
      return true;
    }
    if (message.type === 'robot_state' &&
        (active.kind === 'joint' || active.kind === 'multi' || active.kind === 'home') && active.completeReceived) {
      const observedAtMs = finiteNumber(message.observedAtMs ?? message.ts ?? this.now());
      const joints = message.joints || message.jointsDeg;
      if (!Array.isArray(joints) || joints.length !== 6 || observedAtMs < active.completedAtMs) return false;
      if (active.kind === 'multi') {
        const errorsDeg = active.targetJointsDeg.map(
          (target, index) => Math.abs(Number(joints[index]) - target)
        );
        if (!errorsDeg.every(Number.isFinite)) return false;
        const missed = active.changedJointIndices.filter(
          index => errorsDeg[index] > this.jointToleranceDeg
        );
        if (missed.length === 0 && errorsDeg.every(
          errorDeg => errorDeg <= this.jointToleranceDeg
        )) {
          this._finish(
            true, 'success',
            `多轴运动完成，六轴最大目标误差 ${Math.max(...errorsDeg).toFixed(2)}°`
          );
        } else {
          this._finish(
            false, 'failed',
            `多轴运动未到位：${missed.map(index => `J${index + 1} 误差 ${errorsDeg[index].toFixed(2)}°`).join('；') || '其他关节偏离目标'}`
          );
        }
        return true;
      }
      if (active.kind === 'home') {
        const errorsDeg = active.targetJointsDeg.map(
          (target, index) => Math.abs(Number(joints[index]) - target)
        );
        if (errorsDeg.every(Number.isFinite) &&
            errorsDeg.every(errorDeg => errorDeg <= this.jointToleranceDeg)) {
          this._finish(
            true,
            'success',
            `已返回右侧 Home 预设位置，六轴最大误差 ${Math.max(...errorsDeg).toFixed(2)}°`
          );
        } else {
          const maxErrorDeg = errorsDeg.every(Number.isFinite) ? Math.max(...errorsDeg) : null;
          this._finish(
            false,
            'failed',
            maxErrorDeg === null
              ? 'Home 完成后未收到有效六轴反馈'
              : `Home 未到位，六轴最大误差 ${maxErrorDeg.toFixed(2)}°`
          );
        }
        return true;
      }
      const actual = finiteNumber(joints[active.jointIndex]);
      if (actual === null) return false;
      const errorDeg = Math.abs(actual - active.targetDeg);
      if (errorDeg <= this.jointToleranceDeg) {
        this._finish(
          true,
          'success',
          `J${active.jointIndex + 1} 已达到 ${actual.toFixed(2)}°，目标误差 ${errorDeg.toFixed(2)}°`
        );
      } else {
        this._finish(
          false,
          'failed',
          `J${active.jointIndex + 1} 未达到目标：实际 ${actual.toFixed(2)}°，误差 ${errorDeg.toFixed(2)}°`
        );
      }
      return true;
    }
    return false;
  }

  _execute(session, candidate, params) {
    if (this.active) return this._blocked(session, candidate, '已有 Language 动作正在执行');

    const state = this.getRobotState() || {};
    const ageMs = finiteNumber(state.ageMs);
    if (!state.connected) return this._blocked(session, candidate, 'Startouch SDK 未连接');
    if (!state.stateFresh || ageMs === null || ageMs > this.stateMaxAgeMs) {
      return this._blocked(session, candidate, '机器人状态超过 500ms 或尚未就绪');
    }
    if (state.motionActive || state.moving || state.activeViewActive || state.graspActive) {
      return this._blocked(session, candidate, '机器人或其他控制流程正在占用运动通道');
    }
    if (state.stateName && state.stateName !== 'IDLE') {
      return this._blocked(session, candidate, `机器人状态不是 IDLE: ${state.stateName}`);
    }

    if (params.action === 'robot.status') {
      return this._send(session, 'skill.result', {
        success: true,
        status: 'success',
        candidateId: candidate.candidateId,
        traceId: candidate.traceId,
        message: '机器人状态读取成功',
        hardware: clone(state),
      });
    }
    if (!this.enabled) return this._blocked(session, candidate, 'LANGUAGE_REAL_CONTROL 未启用，未发送硬件命令');

    if (params.action === 'robot.home') {
      const target = this.getHomeTarget();
      if (!Array.isArray(target) || target.length !== 6 || !target.every(Number.isFinite)) {
        return this._blocked(session, candidate, '右侧 Home 预设尚未就绪');
      }
      const outsideLimits = target.flatMap((value, index) => {
        const limits = this.jointLimitsDeg[index];
        if (Array.isArray(limits) && limits.length === 2 && limits.every(Number.isFinite) &&
            value >= limits[0] && value <= limits[1]) return [];
        const range = Array.isArray(limits) && limits.length === 2
          ? `允许 ${limits[0]}°～${limits[1]}°` : '限位数据缺失';
        return [`J${index + 1} 目标 ${value.toFixed(1)}° 超出机械关节限位（${range}）`];
      });
      if (outsideLimits.length) {
        return this._blocked(session, candidate, `Home 机械限位禁止执行：${outsideLimits.join('；')}`);
      }
      const requestId = this.makeRequestId();
      const timeSec = this.moveTimeFor(target);
      const timeoutMs = Math.min(
        this.maxHomeTimeoutMs,
        Math.max(1000, (timeSec + 5) * 1000)
      );
      this._begin({
        session,
        candidate,
        requestId,
        kind: 'home',
        targetJointsDeg: [...target],
        label: 'Home 预设运动',
        timeoutMs,
      });
      const sent = this.sendRobot({
        cmd: 'preset_home',
        name: 'home',
        request_id: requestId,
        time_sec: timeSec,
        source: `language:${candidate.traceId}`,
      });
      if (!sent) this._finish(false, 'failed', 'Startouch bridge 拒绝接收 Home 预设命令');
      return sent;
    }

    if (params.action === 'joint.multi') {
      const current = state.jointsDeg;
      if (!Array.isArray(current) || current.length !== 6 || !current.every(Number.isFinite)) {
        return this._blocked(session, candidate, '缺少有效的六轴实时状态');
      }
      const target = [...current];
      const changedJointIndices = [];
      const violations = [];
      for (const move of params.moves) {
        const index = move.joint - 1;
        target[index] = 'targetDeg' in move ? move.targetDeg : current[index] + move.deltaDeg;
        const delta = target[index] - current[index];
        if (Math.abs(delta) > 0.01) changedJointIndices.push(index);
        if (this.maxDeltaDeg !== null && Math.abs(delta) > this.maxDeltaDeg + 1e-9) {
          violations.push(`J${move.joint} 单次变化 ${Math.abs(delta).toFixed(2)}° 超过 ${this.maxDeltaDeg}°`);
        }
      }
      for (let index = 0; index < 6; index += 1) {
        const limits = this.jointLimitsDeg[index];
        if (!Array.isArray(limits) || limits.length !== 2 || !limits.every(Number.isFinite) ||
            !Number.isFinite(target[index]) || target[index] < limits[0] || target[index] > limits[1]) {
          const range = Array.isArray(limits) && limits.length === 2
            ? `允许 ${limits[0]}°～${limits[1]}°` : '限位数据缺失';
          violations.push(`J${index + 1} 目标 ${target[index].toFixed(1)}° 超出机械关节限位（${range}）`);
        }
      }
      if (violations.length) {
        return this._blocked(session, candidate, `机械限位禁止执行：${violations.join('；')}`);
      }
      if (changedJointIndices.length === 0) {
        return this._blocked(session, candidate, '多轴目标与当前姿态相同，未发送运动命令');
      }
      const requestId = this.makeRequestId();
      const timeSec = this.moveTimeFor(target);
      const timeoutMs = Math.min(
        this.maxMultiTimeoutMs, Math.max(1000, (timeSec + 3) * 1000)
      );
      this._begin({
        session, candidate, requestId, kind: 'multi',
        targetJointsDeg: target, changedJointIndices,
        label: '多轴运动', timeoutMs,
      });
      const sent = this.sendRobot({
        cmd: 'move_joint',
        joints_rad: target.map(value => value * Math.PI / 180),
        time_sec: timeSec,
        request_id: requestId,
        source: `language:${candidate.traceId}`,
        speed_scale: this.speedScale,
        manual_joint_authorization: {
          skill: MANUAL_SKILL, action: 'joint.multi', moves: params.moves,
        },
      });
      if (!sent) this._finish(false, 'failed', 'Startouch bridge 拒绝接收多轴关节命令');
      return sent;
    }

    if (params.action === 'joint.set' || params.action === 'joint.step') {
      const current = state.jointsDeg;
      if (!Array.isArray(current) || current.length !== 6 || !current.every(Number.isFinite)) {
        return this._blocked(session, candidate, '缺少有效的六轴实时状态');
      }
      const jointIndex = params.joint - 1;
      const targetDeg = params.action === 'joint.set'
        ? Number(params.targetDeg)
        : current[jointIndex] + Number(params.deltaDeg);
      const deltaDeg = targetDeg - current[jointIndex];
      if (this.maxDeltaDeg !== null && Math.abs(deltaDeg) > this.maxDeltaDeg + 1e-9) {
        return this._blocked(session, candidate, `单次关节变化 ${Math.abs(deltaDeg).toFixed(2)}° 超过 ${this.maxDeltaDeg}°`);
      }
      const limits = this.jointLimitsDeg[jointIndex];
      if (!Array.isArray(limits) || limits.length !== 2 || !limits.every(Number.isFinite) ||
          targetDeg < limits[0] || targetDeg > limits[1]) {
        const range = Array.isArray(limits) && limits.length === 2
          ? `允许 ${limits[0]}°～${limits[1]}°` : '限位数据缺失';
        return this._blocked(session, candidate,
          `J${params.joint} 目标 ${targetDeg.toFixed(1)}° 超出机械关节限位（${range}）`);
      }
      const target = [...current];
      target[jointIndex] = targetDeg;
      const requestId = this.makeRequestId();
      const timeSec = this.moveTimeFor(target);
      const timeoutMs = Math.min(this.maxJointTimeoutMs, Math.max(1000, (timeSec + 3) * 1000));
      this._begin({
        session,
        candidate,
        requestId,
        kind: 'joint',
        jointIndex,
        targetDeg,
        label: `J${params.joint} 运动`,
        timeoutMs,
      });
      const sent = this.sendRobot({
        cmd: 'move_joint',
        joints_rad: target.map(value => value * Math.PI / 180),
        time_sec: timeSec,
        request_id: requestId,
        source: `language:${candidate.traceId}`,
        speed_scale: this.speedScale,
      });
      if (!sent) this._finish(false, 'failed', 'Startouch bridge 拒绝接收关节命令');
      return sent;
    }

    const target = params.action === 'gripper.open'
      ? this.gripperOpenTarget
      : this.gripperCloseTarget;
    const requestId = this.makeRequestId();
    const label = params.action === 'gripper.open' ? '夹爪打开' : '夹爪闭合';
    this._begin({ session, candidate, requestId, kind: 'gripper', label, timeoutMs: this.gripperTimeoutMs });
    const sent = this.sendRobot({ cmd: 'gripper', position: target, request_id: requestId });
    if (!sent) this._finish(false, 'failed', 'Startouch bridge 拒绝接收夹爪命令');
    return sent;
  }

  _executeStop(session, candidate) {
    if (!this.enabled) {
      return this._blocked(session, candidate, 'LANGUAGE_REAL_CONTROL 未启用，软件停止未发送');
    }
    if (this.active) {
      this.softwareStop();
      this._finish(false, 'failed', '收到软件停止请求，原动作结果不确定');
    }
    const requestId = this.makeRequestId();
    this._begin({ session, candidate, requestId, kind: 'stop', label: '软件停止', timeoutMs: 5000 });
    const accepted = this.softwareStop();
    if (!accepted) this._finish(false, 'failed', 'Startouch SDK 未连接，软件停止未被接受');
    return accepted;
  }

  _begin(active) {
    this.active = {
      ...active,
      completeReceived: false,
      completedAtMs: null,
      timer: null,
    };
    this._send(active.session, 'execution.request', {
      requestId: active.requestId,
      candidateId: active.candidate.candidateId,
      traceId: active.candidate.traceId,
      skill: active.candidate.skill,
      action: active.candidate.payload?.params?.action,
    });
    this.active.timer = this.schedule(() => {
      if (!this.active || this.active.requestId !== active.requestId) return;
      this.softwareStop();
      this._finish(false, 'failed', `${active.label}超时，已请求软件停止；最终硬件状态不确定`);
    }, active.timeoutMs);
  }

  _blocked(session, candidate, message) {
    return this._send(session, 'skill.result', {
      success: false,
      status: 'blocked',
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      message,
    });
  }

  _finish(success, status, message) {
    const active = this.active;
    if (!active) return false;
    if (active.timer) this.cancelSchedule(active.timer);
    this.active = null;
    const result = {
      success,
      status,
      requestId: active.requestId,
      candidateId: active.candidate.candidateId,
      traceId: active.candidate.traceId,
      skill: active.candidate.skill,
      action: active.candidate.payload?.params?.action,
      message,
      simulated: this.getRobotState()?.simulated === true,
    };
    this._send(active.session, 'execution.result', result);
    this._send(active.session, 'skill.result', result);
    return true;
  }

  _send(session, type, payload) {
    this.onMessage(session, { type, ...payload, ts: this.now() });
    return payload;
  }

  _prune() {
    const now = this.now();
    for (const [candidateId, expiry] of this.consumed) {
      if (expiry <= now) this.consumed.delete(candidateId);
    }
    for (const [session, pending] of this.sessions) {
      for (const [candidateId, registered] of pending) {
        if (registered.expiresAtMs <= now) pending.delete(candidateId);
      }
      if (pending.size === 0) this.sessions.delete(session);
    }
  }
}

module.exports = {
  ALLOWED_ACTIONS,
  MANUAL_SKILL,
  ManualJointOrchestrator,
  normalizeMultiJointMoves,
  validateCandidate,
};
