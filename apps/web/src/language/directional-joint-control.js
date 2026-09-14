'use strict';

const { randomUUID } = require('crypto');
const { forwardKinematicsPosition } = require('./startouch-forward-kinematics');

const DIRECTIONAL_SKILL = 'directional_joint_control@1';
const DIRECTIONAL_MAPPING = Object.freeze({
  'turn.left': Object.freeze([[0, 1]]),
  'turn.right': Object.freeze([[0, -1]]),
  'lift.up': Object.freeze([[1, 1], [2, -1]]),
  'lift.down': Object.freeze([[1, -1], [2, 1]]),
  'wrist.pitch.up': Object.freeze([[3, -1]]),
  'wrist.pitch.down': Object.freeze([[3, 1]]),
  'wrist.yaw.left': Object.freeze([[4, 1]]),
  'wrist.yaw.right': Object.freeze([[4, -1]]),
  'wrist.roll.clockwise': Object.freeze([[5, 1]]),
  'wrist.roll.counterclockwise': Object.freeze([[5, -1]]),
});
const DIRECTIONAL_ACTIONS = new Set(Object.keys(DIRECTIONAL_MAPPING));
const DIRECTIONAL_FAMILIES = Object.freeze({
  'turn.left': 'turn',
  'turn.right': 'turn',
  'lift.up': 'lift',
  'lift.down': 'lift',
  'wrist.pitch.up': 'wrist.pitch',
  'wrist.pitch.down': 'wrist.pitch',
  'wrist.yaw.left': 'wrist.yaw',
  'wrist.yaw.right': 'wrist.yaw',
  'wrist.roll.clockwise': 'wrist.roll',
  'wrist.roll.counterclockwise': 'wrist.roll',
});

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function finiteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeDirectionalMoves(params) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) {
    return { ok: false, reason: 'payload.params 必须是对象' };
  }
  const keys = Object.keys(params).sort().join(',');
  if (keys === 'action,deltaDeg') {
    const deltaDeg = finiteNumber(params.deltaDeg);
    if (!DIRECTIONAL_ACTIONS.has(params.action) || deltaDeg === null || deltaDeg <= 0) {
      return { ok: false, reason: '方向 action 或 deltaDeg 无效' };
    }
    return {
      ok: true,
      moves: [{ action: params.action, deltaDeg }],
      compound: false,
    };
  }
  if (keys !== 'moves' || !Array.isArray(params.moves) ||
      params.moves.length < 2 || params.moves.length > 5) {
    return { ok: false, reason: 'payload.params 必须是单动作或包含 2–5 项的 moves' };
  }
  const families = new Set();
  const moves = [];
  for (const move of params.moves) {
    if (!move || typeof move !== 'object' || Array.isArray(move) ||
        Object.keys(move).sort().join(',') !== 'action,deltaDeg') {
      return { ok: false, reason: '每个方向动作只允许 action 和 deltaDeg' };
    }
    const deltaDeg = finiteNumber(move.deltaDeg);
    const family = DIRECTIONAL_FAMILIES[move.action];
    if (!family || deltaDeg === null || deltaDeg <= 0) {
      return { ok: false, reason: '组合方向 action 或 deltaDeg 无效' };
    }
    if (families.has(family)) {
      return { ok: false, reason: `组合方向不能重复或冲突: ${family}` };
    }
    families.add(family);
    moves.push({ action: move.action, deltaDeg });
  }
  return { ok: true, moves, compound: true };
}

function validateDirectionalCandidate(candidate, nowMs) {
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return { ok: false, reason: 'candidate 必须是对象' };
  }
  for (const field of ['candidateId', 'traceId', 'sourceText', 'skill', 'intent']) {
    if (typeof candidate[field] !== 'string' || !candidate[field].trim()) {
      return { ok: false, reason: `${field} 必须是非空字符串` };
    }
  }
  if (candidate.skill !== DIRECTIONAL_SKILL) {
    return { ok: false, reason: `不支持的 Skill: ${candidate.skill}` };
  }
  const createdAt = finiteNumber(candidate.createdAt);
  const expiresAtMs = finiteNumber(candidate.expiresAt);
  if (!Number.isInteger(createdAt) || !Number.isInteger(expiresAtMs)) {
    return { ok: false, reason: 'createdAt/expiresAt 必须是整数时间戳' };
  }
  if (expiresAtMs <= nowMs || expiresAtMs <= createdAt) {
    return { ok: false, reason: '候选已过期或有效期无效' };
  }
  if (expiresAtMs - createdAt > 120_000 || expiresAtMs - nowMs > 120_000) {
    return { ok: false, reason: '候选有效期不得超过 120 秒' };
  }
  if (candidate.requiresConfirmation !== true) {
    return { ok: false, reason: '方向动作必须显式确认' };
  }
  const params = candidate.payload?.params;
  const normalized = normalizeDirectionalMoves(params);
  if (!normalized.ok) return normalized;
  const expectedIntent = normalized.compound ? 'directional.compound' : normalized.moves[0].action;
  if (candidate.intent !== expectedIntent) {
    return { ok: false, reason: '方向 intent 与动作结构不匹配' };
  }
  return {
    ok: true,
    expiresAtMs,
    params: normalized.compound
      ? { moves: normalized.moves }
      : { ...normalized.moves[0] },
  };
}

function computeDirectionalTarget({
  currentJointsDeg,
  moves,
  action,
  deltaDeg,
  jointLimitsDeg,
  forwardKinematics = forwardKinematicsPosition,
}) {
  if (!Array.isArray(currentJointsDeg) || currentJointsDeg.length !== 6 ||
      !currentJointsDeg.every(Number.isFinite)) {
    return { ok: false, reason: '缺少有效的六轴实时状态' };
  }
  const normalized = normalizeDirectionalMoves(
    Array.isArray(moves) ? { moves } : { action, deltaDeg }
  );
  if (!normalized.ok) return normalized;
  const targetJointsDeg = [...currentJointsDeg];
  const changedJointIndices = new Set();
  for (const move of normalized.moves) {
    for (const [index, sign] of DIRECTIONAL_MAPPING[move.action]) {
      targetJointsDeg[index] += sign * move.deltaDeg;
      changedJointIndices.add(index);
    }
  }
  for (const index of changedJointIndices) {
    const limits = jointLimitsDeg?.[index];
    const target = targetJointsDeg[index];
    if (!Array.isArray(limits) || limits.length !== 2 || !limits.every(Number.isFinite) ||
        target < limits[0] || target > limits[1]) {
      return { ok: false, reason: `J${index + 1} 目标 ${target.toFixed(1)}° 超出机械关节限位` };
    }
  }

  let displacementM = null;
  const liftMove = normalized.moves.find(
    move => move.action === 'lift.up' || move.action === 'lift.down'
  );
  if (liftMove) {
    const liftOnlyTarget = [...currentJointsDeg];
    for (const [index, sign] of DIRECTIONAL_MAPPING[liftMove.action]) {
      liftOnlyTarget[index] += sign * liftMove.deltaDeg;
    }
    let currentPosition;
    let targetPosition;
    try {
      currentPosition = forwardKinematics(currentJointsDeg);
      targetPosition = forwardKinematics(liftOnlyTarget);
    } catch (error) {
      return { ok: false, reason: `整体升降运动学校验失败: ${error.message}` };
    }
    if (!Array.isArray(currentPosition) || !Array.isArray(targetPosition) ||
        currentPosition.length !== 3 || targetPosition.length !== 3 ||
        !currentPosition.every(Number.isFinite) || !targetPosition.every(Number.isFinite)) {
      return { ok: false, reason: '整体升降运动学返回无效位置' };
    }
    displacementM = targetPosition.map((value, index) => value - currentPosition[index]);
    const [dx, dy, dz] = displacementM;
    const transverse = Math.hypot(dx, dy);
    const signMatches = liftMove.action === 'lift.up' ? dz > 1e-6 : dz < -1e-6;
    if (!signMatches || Math.abs(dz) + 1e-9 < transverse) {
      const label = liftMove.action === 'lift.up' ? '抬高' : '降低';
      return {
        ok: false,
        reason: `${label}动作未通过基坐标方向校验（dz=${dz.toFixed(4)}m, 横向=${transverse.toFixed(4)}m）`,
      };
    }
  }
  return {
    ok: true,
    targetJointsDeg,
    changedJointIndices: [...changedJointIndices].sort((a, b) => a - b),
    displacementM,
  };
}

class DirectionalJointOrchestrator {
  constructor(options = {}) {
    this.enabled = options.enabled === true;
    this.realControlEnabled = options.realControlEnabled === true;
    this.getRobotState = options.getRobotState || (() => ({}));
    this.sendRobot = options.sendRobot || (() => false);
    this.softwareStop = options.softwareStop || (() => false);
    this.moveTimeFor = options.moveTimeFor || (() => 0.5);
    this.onMessage = options.onMessage || (() => {});
    this.now = options.now || Date.now;
    this.makeRequestId = options.makeRequestId || randomUUID;
    this.schedule = options.schedule || setTimeout;
    this.cancelSchedule = options.cancelSchedule || clearTimeout;
    this.jointLimitsDeg = options.jointLimitsDeg || [];
    this.forwardKinematics = options.forwardKinematics || forwardKinematicsPosition;
    this.speedScale = Number(options.speedScale ?? 0.05);
    this.stateMaxAgeMs = Number(options.stateMaxAgeMs ?? 500);
    this.jointToleranceDeg = Number(options.jointToleranceDeg ?? 1);
    this.maxJointTimeoutMs = Number(options.maxJointTimeoutMs ?? 35_000);
    this.sessions = new Map();
    this.consumed = new Map();
    this.active = null;
  }

  runtimeConfig() {
    return {
      enabled: this.enabled,
      realControlEnabled: this.realControlEnabled,
      skill: DIRECTIONAL_SKILL,
      actions: [...DIRECTIONAL_ACTIONS],
      defaultDeltaDeg: 20,
      speedScale: this.speedScale,
      stateMaxAgeMs: this.stateMaxAgeMs,
      jointToleranceDeg: this.jointToleranceDeg,
    };
  }

  register(session, candidate) {
    this._prune();
    if (!this.enabled) {
      return this._send(session, 'skill.candidate.rejected', {
        candidateId: candidate?.candidateId || null,
        traceId: candidate?.traceId || null,
        reason: 'DIRECTIONAL_CONTROL_ENABLED 未启用',
      });
    }
    const checked = validateDirectionalCandidate(candidate, this.now());
    if (!checked.ok) {
      return this._send(session, 'skill.candidate.rejected', {
        candidateId: candidate?.candidateId || null,
        traceId: candidate?.traceId || null,
        reason: checked.reason,
      });
    }
    if (this.consumed.has(candidate.candidateId)) {
      return this._send(session, 'skill.candidate.rejected', {
        candidateId: candidate.candidateId,
        traceId: candidate.traceId,
        reason: '候选已消费，禁止重放',
      });
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
    return this._execute(session, registered.candidate, registered.params);
  }

  disconnect(session) {
    this.sessions.delete(session);
    if (this.active?.session === session) {
      this._abort('控制页面断开，已请求软件停止；执行结果不确定');
    }
  }

  handleBridgeEvent(message) {
    const active = this.active;
    if (!active || !message || typeof message !== 'object') return false;
    if (message.type === 'connection' && message.connected === false) {
      this._abort(message.error || message.reason || 'Startouch SDK 连接中断，执行结果不确定');
      return true;
    }
    const requestId = message.request_id || message.requestId;
    if (requestId && requestId !== active.requestId) return false;
    if (message.type === 'error') {
      this._abort(message.message || '方向硬件命令失败');
      return true;
    }
    if (message.type === 'command_complete') {
      active.completeReceived = true;
      active.completedAtMs = this.now();
      return true;
    }
    if (message.type !== 'robot_state' || !active.completeReceived) return false;
    const observedAtMs = finiteNumber(message.observedAtMs ?? message.ts ?? this.now());
    const joints = message.joints || message.jointsDeg;
    if (!Array.isArray(joints) || joints.length !== 6 || !joints.every(Number.isFinite) ||
        observedAtMs === null || observedAtMs < active.completedAtMs ||
        (message.stateName && message.stateName !== 'IDLE')) return false;
    const errorsDeg = active.targetJointsDeg.map(
      (target, index) => Math.abs(target - joints[index])
    );
    const maxErrorDeg = Math.max(...errorsDeg);
    if (errorsDeg.every(errorDeg => errorDeg <= this.jointToleranceDeg)) {
      this._finish(
        true,
        'success',
        `${active.label}完成，六轴最大目标误差 ${maxErrorDeg.toFixed(2)}°`,
        { actualJointsDeg: [...joints], maxErrorDeg }
      );
    } else {
      this._abort(`${active.label}未到位，六轴最大目标误差 ${maxErrorDeg.toFixed(2)}°`);
    }
    return true;
  }

  _execute(session, candidate, params) {
    if (this.active) return this._blocked(session, candidate, '已有 Directional Language 动作正在执行');
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
    const planned = computeDirectionalTarget({
      currentJointsDeg: state.jointsDeg,
      moves: params.moves,
      action: params.action,
      deltaDeg: params.deltaDeg,
      jointLimitsDeg: this.jointLimitsDeg,
      forwardKinematics: this.forwardKinematics,
    });
    if (!planned.ok) return this._blocked(session, candidate, planned.reason);
    if (!this.realControlEnabled) {
      return this._blocked(session, candidate, 'DIRECTIONAL_REAL_CONTROL 未启用，未发送硬件命令');
    }

    const requestId = this.makeRequestId();
    const timeSec = this.moveTimeFor(planned.targetJointsDeg);
    const timeoutMs = Math.min(
      this.maxJointTimeoutMs,
      Math.max(1000, (timeSec + 3) * 1000)
    );
    const normalized = normalizeDirectionalMoves(params);
    const label = normalized.moves.map(move => `${move.action} ${move.deltaDeg}°`).join(' + ');
    this._begin({
      session,
      candidate,
      requestId,
      targetJointsDeg: planned.targetJointsDeg,
      changedJointIndices: planned.changedJointIndices,
      simulated: state.simulated === true,
      label,
      timeoutMs,
    });
    const sent = this.sendRobot({
      cmd: 'move_joint',
      joints_rad: planned.targetJointsDeg.map(value => value * Math.PI / 180),
      time_sec: timeSec,
      request_id: requestId,
      source: `language:${candidate.traceId}`,
      speed_scale: this.speedScale,
      directional_authorization: normalized.compound
        ? { skill: DIRECTIONAL_SKILL, moves: normalized.moves }
        : { skill: DIRECTIONAL_SKILL, ...normalized.moves[0] },
    });
    if (!sent) this._abort('正式 3000 转发拒绝接收方向关节命令');
    return sent;
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
      skill: DIRECTIONAL_SKILL,
      targetJointsDeg: [...active.targetJointsDeg],
      speedScale: this.speedScale,
    });
    this.active.timer = this.schedule(() => {
      if (this.active?.requestId === active.requestId) {
        this._abort(`${active.label}执行超时，结果不确定`);
      }
    }, active.timeoutMs);
  }

  _abort(message) {
    if (!this.active) return false;
    this.softwareStop();
    this._finish(false, 'failed', message);
    return true;
  }

  _finish(success, status, message, extra = {}) {
    const active = this.active;
    if (!active) return false;
    if (active.timer) this.cancelSchedule(active.timer);
    this.active = null;
    return this._send(active.session, 'skill.result', {
      success,
      status,
      candidateId: active.candidate.candidateId,
      traceId: active.candidate.traceId,
      requestId: active.requestId,
      skill: DIRECTIONAL_SKILL,
      simulated: active.simulated,
      message,
      targetJointsDeg: [...active.targetJointsDeg],
      ...extra,
    });
  }

  _blocked(session, candidate, message) {
    return this._send(session, 'skill.result', {
      success: false,
      status: 'blocked',
      candidateId: candidate?.candidateId || null,
      traceId: candidate?.traceId || null,
      skill: DIRECTIONAL_SKILL,
      message,
    });
  }

  _send(session, type, payload) {
    this.onMessage(session, { type, ...payload });
    return true;
  }

  _prune() {
    const nowMs = this.now();
    for (const [candidateId, expiresAtMs] of this.consumed) {
      if (expiresAtMs <= nowMs) this.consumed.delete(candidateId);
    }
    for (const [session, pending] of this.sessions) {
      for (const [candidateId, registered] of pending) {
        if (registered.expiresAtMs <= nowMs) pending.delete(candidateId);
      }
      if (pending.size === 0) this.sessions.delete(session);
    }
  }
}

module.exports = {
  DIRECTIONAL_ACTIONS,
  DIRECTIONAL_MAPPING,
  DIRECTIONAL_SKILL,
  DirectionalJointOrchestrator,
  computeDirectionalTarget,
  normalizeDirectionalMoves,
  validateDirectionalCandidate,
};
