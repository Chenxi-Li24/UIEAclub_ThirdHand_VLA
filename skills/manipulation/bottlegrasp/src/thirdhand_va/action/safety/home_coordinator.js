'use strict';

const { randomUUID } = require('node:crypto');

const { evaluateHomeJoints, evaluateHomeState } = require('./home_gate');

function jointRanges(value) {
  return Array.isArray(value) && value.length === 6 && value.every(item =>
    Array.isArray(item) && item.length === 2 && item.every(Number.isFinite) &&
    item[0] <= item[1]
  );
}

function jointsInsideRanges(joints, ranges) {
  return Array.isArray(joints) && joints.length === 6 && joints.every(
    (value, index) => Number.isFinite(value) &&
      value >= ranges[index][0] && value <= ranges[index][1]
  );
}

class HomeCoordinator {
  constructor({
    robotClient,
    homePreset,
    homeJointsDeg,
    toleranceDeg,
    startupValidated = false,
    startupJointRangesDeg = null,
    timeoutMs = 45000,
    stopAckTimeoutMs = 2000,
    idFactory = randomUUID,
    onStatus = () => {},
  } = {}) {
    if (!robotClient || typeof robotClient.send !== 'function' ||
        typeof robotClient.getRobotState !== 'function' ||
        typeof homePreset !== 'string' || !homePreset ||
        !Number.isSafeInteger(timeoutMs) || timeoutMs <= 0 ||
        !Number.isSafeInteger(stopAckTimeoutMs) || stopAckTimeoutMs <= 0 ||
        typeof idFactory !== 'function' || typeof onStatus !== 'function') {
      throw new TypeError('home coordinator dependencies are invalid');
    }
    this.robotClient = robotClient;
    this.homePreset = homePreset;
    this.homeJointsDeg = Array.isArray(homeJointsDeg) ? [...homeJointsDeg] : homeJointsDeg;
    this.toleranceDeg = toleranceDeg;
    this.startupValidated = startupValidated === true;
    this.startupJointRangesDeg = jointRanges(startupJointRangesDeg)
      ? startupJointRangesDeg.map(item => Object.freeze([...item])) : null;
    this.timeoutMs = timeoutMs;
    this.stopAckTimeoutMs = stopAckTimeoutMs;
    this.idFactory = idFactory;
    this.onStatus = onStatus;
    this.phase = 'idle';
    this.reason = null;
    this.inFlightRequestId = null;
    this.stopRequestId = null;
    this.stopAcknowledged = false;
    this.stopAppliedStateSequence = null;
    this.stopAppliedProducerMonotonicNs = null;
    this.timer = null;
    this._listener = event => this.onRobotEvent(event);
    robotClient.on?.('event', this._listener);
  }

  get ready() {
    return this.phase === 'ready';
  }

  snapshot() {
    return Object.freeze({
      phase: this.phase,
      ready: this.ready,
      reason: this.reason,
      homePreset: this.homePreset,
      inFlightRequestId: this.inFlightRequestId,
      stopRequestId: this.stopRequestId,
    });
  }

  start() {
    if (this.phase !== 'idle') {
      return { accepted: this.phase !== 'failed', duplicate: true, phase: this.phase,
        ...(this.reason === null ? {} : { reason: this.reason }) };
    }
    this.phase = 'waiting_robot';
    this._publish();
    this.timer = setTimeout(() => this._timeout(), this.timeoutMs);
    this.timer.unref?.();
    this._attempt();
    return this.phase === 'failed'
      ? { accepted: false, reason: this.reason }
      : { accepted: true, phase: this.phase };
  }

  onRobotEvent(event = {}) {
    if (this.phase === 'stopping') return this._onStopEvent(event);
    if (this.phase === 'waiting_robot' && event.type === 'robot_state') {
      this._attempt();
      return { handled: true, phase: this.phase };
    }
    if (this.phase !== 'homing') return { handled: false, reason: 'home_inactive' };
    if (event.type === 'connection' && event.connected === false) {
      this._fail('robot_disconnected');
      return { handled: true, accepted: false, reason: this.reason };
    }
    if (!['command_complete', 'error'].includes(event.type) ||
        event.command !== 'preset' || event.request_id !== this.inFlightRequestId) {
      return { handled: false, reason: 'event_ignored' };
    }
    this.inFlightRequestId = null;
    if (event.type === 'error' || event.reached !== true || event.robot_healthy !== true) {
      this._fail('home_not_verified');
      return { handled: true, accepted: false, reason: this.reason };
    }
    const proof = evaluateHomeJoints({
      jointsDeg: event.actualJointsDeg,
      homeJointsDeg: this.homeJointsDeg,
      toleranceDeg: this.toleranceDeg,
    });
    if (proof.allowed !== true) {
      this._fail('home_not_verified');
      return { handled: true, accepted: false, reason: this.reason };
    }
    this._ready();
    return { handled: true, accepted: true, phase: 'ready' };
  }

  shutdown() {
    this._clearTimer();
    this.robotClient.off?.('event', this._listener);
  }

  _attempt() {
    if (this.phase !== 'waiting_robot') return;
    const robotState = this.robotClient.getRobotState();
    const result = evaluateHomeState({
      robotState,
      homeJointsDeg: this.homeJointsDeg,
      toleranceDeg: this.toleranceDeg,
    });
    if (result.allowed) {
      this._ready();
      return;
    }
    if (result.blockers.includes('home_definition_invalid')) {
      this._fail('home_definition_invalid');
      return;
    }
    if (result.blockers.length !== 1 || result.blockers[0] !== 'robot_not_at_home') return;
    if (!this.startupValidated) {
      this._fail('startup_home_not_validated');
      return;
    }
    if (this.startupJointRangesDeg === null) {
      this._fail('startup_home_range_invalid');
      return;
    }
    if (!jointsInsideRanges(robotState.jointsDeg, this.startupJointRangesDeg)) {
      this._fail('startup_pose_outside_validated_range');
      return;
    }
    const requestId = this.idFactory();
    if (typeof requestId !== 'string' || !requestId) {
      this._fail('home_request_id_invalid');
      return;
    }
    const sent = this.robotClient.send({
      cmd: 'preset', name: this.homePreset, source: 'startup:return_home',
      request_id: requestId,
    }) === true;
    if (!sent) return;
    this.inFlightRequestId = requestId;
    this.phase = 'homing';
    this._publish();
  }

  _timeout() {
    this.timer = null;
    if (!['waiting_robot', 'homing'].includes(this.phase)) return;
    if (this.phase !== 'homing') {
      this._fail('startup_home_timeout');
      return;
    }
    const stopId = this.idFactory();
    if (typeof stopId !== 'string' || !stopId || this.robotClient.send({
      cmd: 'software_stop', source: 'startup:return_home_timeout',
      reason: 'startup_home_timeout', request_id: stopId,
    }) !== true) {
      this._fail('startup_home_stop_unconfirmed');
      return;
    }
    this.inFlightRequestId = null;
    this.stopRequestId = stopId;
    this.stopAcknowledged = false;
    this.stopAppliedStateSequence = null;
    this.stopAppliedProducerMonotonicNs = null;
    this.phase = 'stopping';
    this.reason = 'startup_home_timeout';
    this.timer = setTimeout(
      () => this._fail('startup_home_stop_unconfirmed'), this.stopAckTimeoutMs
    );
    this.timer.unref?.();
    this._publish();
  }

  _onStopEvent(event) {
    if (event.type === 'connection' && event.connected === false) {
      this._fail('startup_home_stop_unconfirmed');
      return { handled: true, accepted: false, reason: this.reason };
    }
    if (event.type === 'robot_state') {
      if (this.robotClient.stopProofMode !== 'fresh_state_boundary' ||
          this.stopAcknowledged !== true) {
        return { handled: false, reason: 'stop_ack_pending' };
      }
      return this._confirmFreshStoppedState();
    }
    if (!['command_complete', 'error'].includes(event.type) ||
        event.command !== 'software_stop' || event.request_id !== this.stopRequestId) {
      return { handled: false, reason: 'event_ignored' };
    }
    if (event.type === 'error') {
      this._fail('startup_home_stop_unconfirmed');
      return { handled: true, accepted: false, reason: this.reason };
    }
    if (this.robotClient.stopProofMode === 'fresh_state_boundary') {
      if (event.stopped !== true ||
          !Number.isSafeInteger(event.applied_state_sequence) ||
          !Number.isSafeInteger(event.applied_producer_monotonic_ns)) {
        this._fail('startup_home_stop_unconfirmed');
        return { handled: true, accepted: false, reason: this.reason };
      }
      this.stopAcknowledged = true;
      this.stopAppliedStateSequence = event.applied_state_sequence;
      this.stopAppliedProducerMonotonicNs = event.applied_producer_monotonic_ns;
      return { handled: true, accepted: true, reason: 'fresh_stopped_state_pending' };
    }
    if (this.robotClient.stopProofMode !== 'cleanup_ack_only' ||
        event.cleanupAcknowledged !== true ||
        !['simulation', 'vendor_cleanup_returned'].includes(
          event.cleanupConfirmationMode
        ) || event.controlReleased !== true ||
        event.depowerIndependentlyConfirmed !== false) {
      this._fail('startup_home_stop_unconfirmed');
      return { handled: true, accepted: false, reason: this.reason };
    }
    this._fail('startup_home_timeout');
    return { handled: true, accepted: true, reason: this.reason };
  }

  _confirmFreshStoppedState() {
    const robot = this.robotClient.getRobotState();
    const afterBoundary = Number.isSafeInteger(robot?.stateSequence) &&
      Number.isSafeInteger(robot?.producerMonotonicNs) &&
      robot.stateSequence > this.stopAppliedStateSequence &&
      robot.producerMonotonicNs > this.stopAppliedProducerMonotonicNs;
    if (!afterBoundary || robot.connected !== true || robot.stateFresh !== true ||
        robot.stationary !== true) {
      return { handled: false, reason: 'fresh_stopped_state_pending' };
    }
    this._fail('startup_home_timeout');
    return { handled: true, accepted: true, reason: this.reason };
  }

  _ready() {
    this._clearTimer();
    this.inFlightRequestId = null;
    this.stopRequestId = null;
    this.phase = 'ready';
    this.reason = null;
    this._publish();
  }

  _fail(reason) {
    this._clearTimer();
    this.inFlightRequestId = null;
    this.stopRequestId = null;
    this.stopAcknowledged = false;
    this.phase = 'failed';
    this.reason = reason;
    this._publish();
  }

  _clearTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  _publish() {
    this.onStatus(this.snapshot());
  }
}

module.exports = { HomeCoordinator };
