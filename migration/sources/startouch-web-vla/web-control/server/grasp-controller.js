'use strict';

const { EventEmitter } = require('events');
const { randomUUID } = require('crypto');

const MAX_PLAN_SHIFT_M = 0.02;
const GRIPPER_MAX_WIDTH_M = 0.08;
const ACTIVE_TARGET_PHASES = new Set([
  'hover',
  'descend',
  'close',
  'lift',
  'preview_ready',
  'awaiting_fresh_preview',
  'awaiting_robot_idle',
]);

function distance(a, b) {
  if (!Array.isArray(a) || !Array.isArray(b)) return Number.POSITIVE_INFINITY;
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function finiteVector(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

class GraspController extends EventEmitter {
  constructor({ sendRobot, authorizePlan, canContinue, maxPlanShiftM = MAX_PLAN_SHIFT_M }) {
    super();
    this.sendRobot = sendRobot;
    this.authorizePlan = authorizePlan;
    this.canContinue = canContinue;
    this.maxPlanShiftM = maxPlanShiftM;
    this.latestTarget = null;
    this.state = this._idle();
  }

  _idle() {
    return { phase: 'idle', mode: null, reason: null, nextPhase: null, inFlight: null };
  }

  snapshot() {
    const { plan, ...publicState } = this.state;
    return { ...publicState };
  }

  updateTarget(target) {
    this.latestTarget = target || null;
    if (ACTIVE_TARGET_PHASES.has(this.state.phase)) {
      const binding = this._checkTargetBinding(this.latestTarget);
      if (!binding.approved) {
        this.cancel(binding.reason);
        return;
      }
    }
    if (this.state.phase !== 'awaiting_fresh_preview') return;
    const checked = this._authorizeBoundTarget();
    if (!checked.approved) {
      if (['target_stale', 'target_timestamp_invalid', 'arm_motion_active', 'robot_state_stale']
        .includes(checked.reason)) return;
      this.cancel(checked.reason);
      return;
    }
    if (checked.plan.observedAtMs <= this.state.plan.observedAtMs ||
        checked.plan.previewId === this.state.plan.previewId) return;
    if (distance(checked.plan.graspM, this.state.plan.graspM) > this.maxPlanShiftM) {
      this.cancel('target_position_shifted');
      return;
    }
    this.state.plan = checked.plan;
    this._dispatch('descend');
  }

  start(mode) {
    if (!['step', 'auto'].includes(mode)) return { ok: false, reason: 'mode_invalid' };
    if (!['idle', 'aborted'].includes(this.state.phase)) {
      return { ok: false, reason: 'grasp_active' };
    }
    const checked = this.authorizePlan(this.latestTarget);
    if (!checked?.approved) return { ok: false, reason: checked?.reason || 'authorization_failed' };
    this.state = {
      phase: 'starting',
      mode,
      reason: null,
      nextPhase: null,
      inFlight: null,
      plan: checked.plan,
      identityId: checked.plan.identityId,
      calibrationId: checked.plan.calibrationId,
    };
    if (!this._dispatch('hover')) return { ok: false, reason: this.state.reason };
    return { ok: true, mode };
  }

  advance() {
    if (this.state.mode !== 'step' || this.state.phase !== 'preview_ready') {
      return { ok: false, reason: 'not_ready_for_step' };
    }
    const phase = this.state.nextPhase;
    const checked = this._reauthorizeBoundPlan();
    if (!checked.approved) {
      this.cancel(checked.reason);
      return { ok: false, reason: checked.reason };
    }
    const gate = this.canContinue();
    if (!gate?.approved) return { ok: false, reason: gate?.reason || 'continuation_blocked' };
    return this._dispatch(phase)
      ? { ok: true, phase }
      : { ok: false, reason: this.state.reason };
  }

  complete(command, requestId = null) {
    if (!this.state.inFlight || this.state.inFlight.command !== command) return false;
    if (this.state.inFlight.requestId && requestId !== this.state.inFlight.requestId) return false;
    const completedPhase = this.state.inFlight.phase;
    this.state.inFlight = null;

    if (completedPhase === 'lift') {
      this._setState('holding', null);
      return true;
    }
    const next = completedPhase === 'hover' ? 'descend' : completedPhase === 'descend' ? 'close' : 'lift';
    if (this.state.mode === 'step') {
      this._setState('preview_ready', null, next);
      return true;
    }
    if (completedPhase === 'hover') {
      this._setState('awaiting_fresh_preview', null, 'descend');
      return true;
    }
    const checked = this._reauthorizeBoundPlan();
    if (!checked.approved) {
      if (checked.reason === 'arm_motion_active') {
        this._setState('awaiting_robot_idle', null, next);
        return true;
      }
      this.cancel(checked.reason);
      return false;
    }
    const gate = this.canContinue();
    if (!gate?.approved) {
      if (gate?.reason === 'arm_motion_active') {
        this._setState('awaiting_robot_idle', null, next);
        return true;
      }
      this.cancel(gate?.reason || 'continuation_blocked');
      return false;
    }
    return this._dispatch(next);
  }

  continueWhenIdle() {
    if (this.state.mode !== 'auto' || this.state.phase !== 'awaiting_robot_idle') return false;
    const checked = this._reauthorizeBoundPlan();
    if (!checked.approved) {
      if (checked.reason === 'arm_motion_active') return false;
      this.cancel(checked.reason);
      return false;
    }
    const gate = this.canContinue();
    if (!gate?.approved) {
      if (gate?.reason === 'arm_motion_active') return false;
      this.cancel(gate?.reason || 'continuation_blocked');
      return false;
    }
    return this._dispatch(this.state.nextPhase);
  }

  fail(reason = 'robot_command_failed') {
    this.cancel(reason);
  }

  cancel(reason = 'operator_cancelled') {
    if (this.state.phase === 'idle') return { ok: true };
    this._setState('aborted', reason);
    return { ok: true, reason };
  }

  _authorizeBoundTarget() {
    const binding = this._checkTargetBinding(this.latestTarget);
    if (!binding.approved) return binding;
    return this.authorizePlan(this.latestTarget, {
      expectedIdentityId: this.state.identityId,
      expectedCalibrationId: this.state.calibrationId,
    });
  }

  _checkTargetBinding(target) {
    if (!target) return { approved: false, reason: 'target_lost' };
    if (target.identityId !== this.state.identityId) {
      return { approved: false, reason: 'target_identity_changed' };
    }
    if (target.calibrationId !== this.state.calibrationId) {
      return { approved: false, reason: 'calibration_changed' };
    }
    if (!finiteVector(target.graspM) || !finiteVector(target.pregraspM) ||
        !finiteVector(target.retreatM) || !Number.isFinite(target.yawRad)) {
      return { approved: false, reason: 'target_position_invalid' };
    }
    return { approved: true };
  }

  _reauthorizeBoundPlan() {
    const checked = this._authorizeBoundTarget();
    if (!checked?.approved) {
      return { approved: false, reason: checked?.reason || 'authorization_failed' };
    }
    if (distance(checked.plan.graspM, this.state.plan.graspM) > this.maxPlanShiftM) {
      return { approved: false, reason: 'target_position_shifted' };
    }
    this.state.plan = checked.plan;
    return checked;
  }

  _dispatch(phase) {
    const plan = this.state.plan;
    let command;
    if (phase === 'hover' || phase === 'descend' || phase === 'lift') {
      const position = phase === 'hover' ? plan.pregraspM : phase === 'descend' ? plan.graspM : plan.retreatM;
      command = {
        cmd: 'move_l',
        position_m: [...position],
        time_sec: phase === 'descend' ? 1.5 : 2.0,
        request_id: `vision_grasp_${randomUUID()}_${phase}`,
      };
    } else if (phase === 'close') {
      command = {
        cmd: 'gripper',
        position: clamp(plan.widthM / GRIPPER_MAX_WIDTH_M, 0, 1),
      };
    } else {
      this.cancel('phase_invalid');
      return false;
    }
    if (!this.sendRobot(command, phase)) {
      this.cancel('robot_command_rejected');
      return false;
    }
    this.state.phase = phase;
    this.state.nextPhase = null;
    this.state.inFlight = {
      phase,
      command: command.cmd,
      requestId: command.request_id || null,
    };
    this._emitStatus();
    return true;
  }

  _setState(phase, reason = null, nextPhase = null) {
    this.state.phase = phase;
    this.state.reason = reason;
    this.state.nextPhase = nextPhase;
    this.state.inFlight = null;
    this._emitStatus();
  }

  _emitStatus() {
    this.emit('status', this.snapshot());
  }
}

module.exports = { GraspController, MAX_PLAN_SHIFT_M };
