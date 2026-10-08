'use strict';

const { randomUUID } = require('node:crypto');
const { GraspController } = require('../grasp/grasp_controller');
const { matchesPreview } = require('./supervised_preview');

class SupervisedTestSession {
  constructor({ previewFactory, currentEvidence, getRobotState, robotClient,
    nowMs = Date.now, commandTimeoutMs = 30000 } = {}) {
    if (typeof previewFactory !== 'function' || typeof currentEvidence !== 'function' ||
        typeof getRobotState !== 'function' || !robotClient ||
        typeof robotClient.send !== 'function' || typeof nowMs !== 'function' ||
        !Number.isFinite(commandTimeoutMs) || commandTimeoutMs <= 0) {
      throw new TypeError('supervised_test_dependencies_invalid');
    }
    this.previewFactory = previewFactory;
    this.currentEvidence = currentEvidence;
    this.getRobotState = getRobotState;
    this.robotClient = robotClient;
    this.nowMs = nowMs;
    this.commandTimeoutMs = commandTimeoutMs;
    this.currentPreview = null;
    this.controller = null;
    this.requestId = null;
    this.phase = 'idle';
    this.expectedEvidence = null;
    this.deadlineMs = null;
    this.timer = null;
    this.stopRequestId = null;
    this.confirmations = new Map();
  }

  preview(targetId) {
    if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5) {
      throw new TypeError('target_id_invalid');
    }
    if (this.controller !== null) throw new TypeError('session_active');
    const preview = this.previewFactory(targetId);
    if (!preview || preview.targetId !== targetId) {
      throw new TypeError('preview_target_mismatch');
    }
    this.currentPreview = preview;
    return preview;
  }

  start({ requestId, previewId } = {}) {
    if (this.controller !== null) return { accepted: false, reason: 'session_active' };
    const preview = this.currentPreview;
    if (!preview || preview.previewId !== previewId || preview.executable !== true ||
        !preview.plan) return { accepted: false, reason: 'preview_not_executable' };
    if (typeof requestId !== 'string' || !requestId ||
        preview.plan.requestId !== requestId) {
      return { accepted: false, reason: 'request_id_mismatch' };
    }
    if (!matchesPreview(preview, this.currentEvidence(), this.nowMs())) {
      return { accepted: false, reason: 'preview_stale' };
    }
    const controller = new GraspController({
      robotClient: this.robotClient,
      getRobotState: this.getRobotState,
    });
    const started = controller.start(preview.plan, { supervised: true });
    if (started.accepted !== true) return started;
    this.controller = controller;
    this.requestId = requestId;
    this.expectedEvidence = this.currentEvidence();
    this.phase = 'awaiting_confirmation';
    return { accepted: true, phase: this.phase, requestId };
  }

  next({ requestId, expectedPhase, confirmationId } = {}) {
    if (typeof confirmationId !== 'string' || !confirmationId) {
      return { accepted: false, reason: 'confirmation_id_invalid' };
    }
    if (this.confirmations.has(confirmationId)) {
      const previous = this.confirmations.get(confirmationId);
      return previous.requestId === requestId && previous.expectedPhase === expectedPhase
        ? previous.response : { accepted: false, reason: 'confirmation_id_reused' };
    }
    if (!this.controller || this.requestId !== requestId ||
        this.phase !== 'awaiting_confirmation') {
      return { accepted: false, reason: 'session_not_waiting' };
    }
    const controllerState = this.controller.snapshot();
    if (controllerState.phase !== expectedPhase ||
        controllerState.awaiting_confirmation !== true) {
      return { accepted: false, reason: 'phase_mismatch' };
    }
    const evidence = this.currentEvidence();
    if (!matchesPreview({ ...this.currentPreview, evidence: this.expectedEvidence,
      createdAtMs: this.nowMs(), expiresAtMs: this.nowMs() + 1 },
    evidence, this.nowMs())) {
      return { accepted: false, reason: 'evidence_changed' };
    }
    if (!controllerState.holdingObject && evidence.targetValid === false) {
      return { accepted: false, reason: 'target_lost' };
    }
    const robot = this.getRobotState();
    if (!robot || robot.connected !== true || robot.healthy !== true ||
        robot.stateFresh !== true || robot.moving === true) {
      return { accepted: false, reason: 'robot_not_stationary' };
    }
    const result = this.controller.advanceSupervised(expectedPhase);
    if (result.accepted !== true) return result;
    this.phase = 'in_flight';
    this.deadlineMs = this.nowMs() + this.commandTimeoutMs;
    this._scheduleTimeout();
    const response = Object.freeze({ accepted: true, phase: this.phase,
      commandRequestId: result.requestId, confirmationId });
    this.confirmations.set(confirmationId, { requestId, expectedPhase, response });
    return response;
  }

  onRobotEvent(event = {}) {
    if (this.phase === 'uncertain_stop' &&
        event.type === 'software_stop_complete' &&
        event.request_id === this.stopRequestId) {
      this.phase = 'stopped';
      return { handled: true, phase: this.phase };
    }
    if (!this.controller || this.phase !== 'in_flight') return { handled: false };
    const result = this.controller.onRobotEvent(event);
    if (result.handled !== true) return result;
    this._clearTimeout();
    const state = this.controller.snapshot();
    if (state.phase === 'complete') this.phase = 'complete';
    else if (state.awaiting_confirmation === true) {
      this.phase = 'awaiting_confirmation';
      this.expectedEvidence = this.currentEvidence();
    } else if (!state.active) this._requestStop('command_failed');
    return { handled: true, phase: this.phase };
  }

  checkTimeout() {
    if (this.phase !== 'in_flight' || this.deadlineMs === null ||
        this.nowMs() < this.deadlineMs) return false;
    this._requestStop('command_timeout');
    return true;
  }

  stop({ requestId } = {}) {
    if (this.phase === 'uncertain_stop' || this.phase === 'stopped') {
      return { accepted: true, duplicate: true, phase: this.phase };
    }
    if (this.requestId !== null && requestId !== this.requestId) {
      return { accepted: false, reason: 'request_id_mismatch' };
    }
    this._requestStop('operator_stop');
    return { accepted: true, phase: this.phase };
  }

  snapshot() {
    const controller = this.controller?.snapshot() ?? null;
    return Object.freeze({
      active: this.controller !== null && !['stopped', 'complete'].includes(this.phase),
      phase: this.phase, requestId: this.requestId,
      commandPhase: controller?.phase ?? null,
      awaiting_confirmation: this.phase === 'awaiting_confirmation',
      inFlightRequestId: controller?.inFlightRequestId ?? null,
      stopRequestId: this.stopRequestId,
    });
  }

  _requestStop() {
    this._clearTimeout();
    this.controller?.cancel('supervised_stop');
    this.phase = 'uncertain_stop';
    if (this.stopRequestId !== null) return;
    this.stopRequestId = randomUUID();
    this.robotClient.send({ cmd: 'software_stop', request_id: this.stopRequestId,
      source: 'supervised_test' });
  }

  _scheduleTimeout() {
    this._clearTimeout(false);
    this.timer = setTimeout(() => this.checkTimeout(), this.commandTimeoutMs);
    this.timer.unref?.();
  }

  _clearTimeout(clearDeadline = true) {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (clearDeadline) this.deadlineMs = null;
  }
}

module.exports = { SupervisedTestSession };
