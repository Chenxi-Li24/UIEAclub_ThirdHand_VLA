'use strict';

const { randomUUID } = require('node:crypto');

const { evaluateHomeJoints } = require('../safety/home_gate');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;
const NEXT_PHASE = Object.freeze({
  open: 'final_approach',
  final_approach: 'close',
  close: 'lift',
  lift: 'transfer',
  transfer: 'lower',
  lower: 'release',
  release: 'retreat',
  retreat: 'return_home',
  return_home: 'complete',
});

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function vector6(value) {
  return Array.isArray(value) && value.length === 6 && value.every(Number.isFinite);
}

function validPhaseDurations(value) {
  const phases = ['final_approach', 'lift', 'transfer', 'lower', 'retreat'];
  return value && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).length === phases.length &&
    phases.every(phase => Number.isFinite(value[phase]) && value[phase] > 0);
}

function sameVector(left, right) {
  return vector3(left) && vector3(right) && left.every(
    (value, index) => Math.abs(value - right[index]) <= 1e-9
  );
}

function validTransferSegments(value, prePlaceM, totalTimeSec) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 64) return false;
  if (!value.every(segment => segment && typeof segment === 'object' &&
      !Array.isArray(segment) && vector3(segment.position) &&
      Number.isFinite(segment.timeSec) && segment.timeSec >= 0.001 &&
      segment.timeSec <= 30)) return false;
  const sum = value.reduce((total, segment) => total + segment.timeSec, 0);
  return Math.abs(sum - totalTimeSec) <= 1e-6 &&
    sameVector(value.at(-1).position, prePlaceM);
}

function validPlan(plan) {
  return plan && plan.schema === 'thirdhand-execution-plan-v2' &&
    Number.isSafeInteger(plan.stableId) && plan.stableId >= 1 && plan.stableId <= 5 &&
    typeof plan.requestId === 'string' && plan.requestId.length > 0 &&
    typeof plan.evidenceId === 'string' && SHA256_ID.test(plan.evidenceId) &&
    Number.isSafeInteger(plan.motionEpoch) && plan.motionEpoch >= 0 &&
    [
      'finalApproachM', 'liftM', 'prePlaceM', 'placeM', 'retreatM',
      'graspEulerRad', 'placeEulerRad',
    ]
      .every(field => vector3(plan[field])) &&
    typeof plan.homePreset === 'string' && plan.homePreset.length > 0 &&
    vector6(plan.homeJointsDeg) &&
    Number.isFinite(plan.homeToleranceDeg) && plan.homeToleranceDeg > 0 &&
    plan.homeToleranceDeg <= 2.0 &&
    Number.isFinite(plan.widthM) && plan.widthM > 0 && plan.widthM <= 0.072 &&
    Number.isFinite(plan.contactMinWidthM) && plan.contactMinWidthM >= 0 &&
    Number.isFinite(plan.contactMaxWidthM) &&
    plan.contactMaxWidthM >= plan.contactMinWidthM &&
    plan.contactMaxWidthM <= 0.072 &&
    Number.isFinite(plan.releaseMinWidthM) &&
    plan.releaseMinWidthM > plan.contactMaxWidthM &&
    Number.isFinite(plan.releaseMaxWidthM) &&
    plan.releaseMaxWidthM >= plan.releaseMinWidthM &&
    plan.releaseMaxWidthM <= 0.080 &&
    validPhaseDurations(plan.timeSecByPhase) &&
    validTransferSegments(
      plan.transferSegments, plan.prePlaceM, plan.timeSecByPhase?.transfer
    ) &&
    Number.isFinite(plan.openPosition) && plan.openPosition >= 0 && plan.openPosition <= 1 &&
    Number.isFinite(plan.closePosition) && plan.closePosition >= 0 && plan.closePosition <= 1 &&
    plan.closePosition < plan.openPosition &&
    typeof plan.pathValidationId === 'string' && SHA256_ID.test(plan.pathValidationId);
}

function freezePlan(plan) {
  const clone = {
    ...plan,
    finalApproachM: Object.freeze([...plan.finalApproachM]),
    liftM: Object.freeze([...plan.liftM]),
    prePlaceM: Object.freeze([...plan.prePlaceM]),
    placeM: Object.freeze([...plan.placeM]),
    retreatM: Object.freeze([...plan.retreatM]),
    graspEulerRad: Object.freeze([...plan.graspEulerRad]),
    placeEulerRad: Object.freeze([...plan.placeEulerRad]),
    homeJointsDeg: Object.freeze([...plan.homeJointsDeg]),
    timeSecByPhase: Object.freeze({ ...plan.timeSecByPhase }),
    transferSegments: Object.freeze(plan.transferSegments.map(segment => Object.freeze({
      position: Object.freeze([...segment.position]),
      timeSec: segment.timeSec,
    }))),
  };
  return Object.freeze(clone);
}

class GraspController {
  constructor({
    robotClient,
    getRobotState = () => null,
    onStatus = () => {},
    idFactory = randomUUID,
  } = {}) {
    if (!robotClient || typeof robotClient.send !== 'function' ||
        typeof getRobotState !== 'function' || typeof onStatus !== 'function' ||
        typeof idFactory !== 'function') {
      throw new TypeError('grasp controller dependencies are invalid');
    }
    this.robotClient = robotClient;
    this.getRobotState = getRobotState;
    this.onStatus = onStatus;
    this.idFactory = idFactory;
    this.plan = null;
    this.phase = 'idle';
    this.reason = null;
    this.failedPhase = null;
    this.inFlight = null;
    this.holdingObject = false;
    this.transferSegmentIndex = 0;
  }

  get active() {
    return !['idle', 'complete', 'failed', 'manual_recovery', 'cancelled']
      .includes(this.phase);
  }

  snapshot() {
    return Object.freeze({
      active: this.active,
      phase: this.phase,
      stableId: this.plan?.stableId ?? null,
      requestId: this.plan?.requestId ?? null,
      evidenceId: this.plan?.evidenceId ?? null,
      motionEpoch: this.plan?.motionEpoch ?? null,
      reason: this.reason,
      failedPhase: this.failedPhase,
      holdingObject: this.holdingObject,
      transferSegmentIndex: this.phase === 'transfer'
        ? this.transferSegmentIndex : null,
      inFlightRequestId: this.inFlight?.requestId ?? null,
      robot_control_enabled: this.active,
    });
  }

  start(plan = {}) {
    if (this.active) return { accepted: false, reason: 'grasp_active' };
    if (plan.executionEnabled === false) {
      return { accepted: false, reason: 'execution_disabled' };
    }
    if (!validPlan(plan)) return { accepted: false, reason: 'execution_plan_invalid' };
    const robot = this.getRobotState();
    if (!robot || robot.connected !== true || robot.healthy !== true ||
        robot.stateFresh !== true) {
      return { accepted: false, reason: 'robot_not_ready' };
    }
    this.plan = freezePlan(plan);
    this.phase = 'open';
    this.reason = null;
    this.failedPhase = null;
    this.inFlight = null;
    this.holdingObject = false;
    this.transferSegmentIndex = 0;
    const sent = this._sendCurrentPhase();
    if (!sent.accepted) return sent;
    return { accepted: true, phase: this.phase, requestId: this.plan.requestId };
  }

  onRobotEvent(event = {}) {
    if (!this.active) return { handled: false, reason: 'grasp_inactive' };
    if (event.type === 'connection' && event.connected === false) {
      return this._fail('robot_disconnected');
    }
    if (event.type === 'software_stop') return this._fail('software_stop');
    if (!this.inFlight || !['command_complete', 'error'].includes(event.type)) {
      return { handled: false, reason: 'event_ignored' };
    }
    if (event.request_id !== this.inFlight.requestId) {
      return { handled: false, reason: 'request_mismatch' };
    }
    if (event.command !== this.inFlight.command) {
      return { handled: false, reason: 'command_mismatch' };
    }
    const completedPhase = this.phase;
    this.inFlight = null;
    if (event.type === 'error') return this._fail(`${completedPhase}_failed`);

    if (completedPhase === 'close') {
      const contactVerified = Number.isFinite(event.actual_width_m) &&
        event.actual_width_m >= this.plan.contactMinWidthM &&
        event.actual_width_m <= this.plan.contactMaxWidthM;
      if (!contactVerified) return this._fail('grasp_contact_not_verified');
      this.holdingObject = true;
    } else if (event.reached !== true) {
      return this._fail(`${completedPhase}_not_reached`);
    }

    if (completedPhase === 'release') {
      const releaseVerified = Number.isFinite(event.actual_width_m) &&
        event.actual_width_m >= this.plan.releaseMinWidthM &&
        event.actual_width_m <= this.plan.releaseMaxWidthM;
      if (!releaseVerified) return this._fail('release_not_verified');
      const robot = this.getRobotState();
      if (event.robot_healthy !== true || !robot || robot.connected !== true ||
          robot.healthy !== true || robot.stateFresh !== true) {
        return this._fail('post_release_path_not_safe');
      }
      this.holdingObject = false;
    }
    if (completedPhase === 'return_home') {
      const home = evaluateHomeJoints({
        jointsDeg: event.actualJointsDeg,
        homeJointsDeg: this.plan.homeJointsDeg,
        toleranceDeg: this.plan.homeToleranceDeg,
      });
      if (event.robot_healthy !== true || home.allowed !== true) {
        return this._fail('home_not_verified');
      }
    }
    if (completedPhase === 'transfer' &&
        this.transferSegmentIndex + 1 < this.plan.transferSegments.length) {
      this.transferSegmentIndex += 1;
      return this._sendCurrentPhase();
    }
    const next = NEXT_PHASE[completedPhase];
    if (next === 'complete') {
      this.phase = 'complete';
      this.reason = null;
      this._publish();
      return { handled: true, accepted: true, phase: 'complete' };
    }
    this.phase = next;
    return this._sendCurrentPhase();
  }

  cancel(reason = 'operator_cancelled') {
    if (!this.active) return { accepted: false, reason: 'grasp_inactive' };
    return this._fail(reason, { cancelled: true });
  }

  finish() {
    if (this.phase === 'complete') return true;
    return false;
  }

  _sendCurrentPhase() {
    const requestId = this.idFactory();
    if (typeof requestId !== 'string' || !requestId) {
      return this._fail('command_request_id_invalid');
    }
    const command = this._commandFor(this.phase, requestId);
    if (this.robotClient.send(command) !== true) {
      return this._fail('robot_transport_unavailable');
    }
    this.inFlight = { requestId, command: command.cmd };
    this._publish();
    return { handled: true, accepted: true, phase: this.phase, requestId };
  }

  _commandFor(phase, requestId) {
    const transferCount = this.plan.transferSegments.length;
    const source = phase === 'transfer' && transferCount > 1
      ? `grasp:transfer:${this.transferSegmentIndex + 1}of${transferCount}`
      : `grasp:${phase}`;
    const common = { request_id: requestId, source };
    if (phase === 'open') {
      return { cmd: 'gripper', position: this.plan.openPosition, ...common };
    }
    if (phase === 'close') {
      return { cmd: 'gripper', position: this.plan.closePosition, ...common };
    }
    if (phase === 'release') {
      return { cmd: 'gripper', position: this.plan.openPosition, ...common };
    }
    if (phase === 'return_home') {
      return { cmd: 'preset', name: this.plan.homePreset, ...common };
    }
    const pointByPhase = {
      final_approach: this.plan.finalApproachM,
      lift: this.plan.liftM,
      transfer: this.plan.transferSegments[this.transferSegmentIndex].position,
      lower: this.plan.placeM,
      retreat: this.plan.retreatM,
    };
    const euler = ['final_approach', 'lift'].includes(phase)
      ? this.plan.graspEulerRad : this.plan.placeEulerRad;
    return {
      cmd: 'move_l',
      position: [...pointByPhase[phase]],
      euler: [...euler],
      time_sec: phase === 'transfer'
        ? this.plan.transferSegments[this.transferSegmentIndex].timeSec
        : this.plan.timeSecByPhase[phase],
      ...common,
    };
  }

  _fail(reason, { cancelled = false } = {}) {
    const failedPhase = this.phase;
    this.inFlight = null;
    this.failedPhase = failedPhase;
    const gripperMayHold = this.holdingObject || [
      'close', 'lift', 'transfer', 'lower', 'release', 'retreat', 'return_home',
    ].includes(failedPhase);
    if (gripperMayHold) {
      this.phase = 'manual_recovery';
      this.reason = ['grasp_contact_not_verified', 'home_not_verified'].includes(reason)
        ? reason : 'manual_recovery_required';
    } else {
      this.phase = cancelled ? 'cancelled' : 'failed';
      this.reason = reason;
    }
    this._publish();
    return {
      handled: true,
      accepted: false,
      phase: this.phase,
      reason: this.reason,
      failedPhase,
    };
  }

  _publish() {
    this.onStatus(this.snapshot());
  }
}

module.exports = { GraspController, NEXT_PHASE };
