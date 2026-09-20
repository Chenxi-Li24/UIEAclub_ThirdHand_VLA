'use strict';

const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');

const ALLOWED_COMMANDS = Object.freeze(new Set([
  'move_l', 'move_joint', 'gripper', 'preset', 'software_stop', 'get_state',
]));

function vector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function validStopBoundary(message, expectedFlight) {
  return Number.isSafeInteger(message.applied_state_sequence) &&
    Number.isSafeInteger(message.applied_producer_monotonic_ns) &&
    Number.isSafeInteger(expectedFlight?.minimumStateSequence) &&
    Number.isSafeInteger(expectedFlight?.minimumProducerMonotonicNs) &&
    message.applied_state_sequence >= expectedFlight.minimumStateSequence &&
    message.applied_producer_monotonic_ns >= expectedFlight.minimumProducerMonotonicNs;
}

class RobotWebSocketClient extends EventEmitter {
  constructor({
    WebSocketImpl,
    url,
    nowNs = process.hrtime.bigint,
    gripperMaxWidthM = 0.080,
    maxStateAgeMs = 250,
    maxStationaryJointSpeedDegS = 0.5,
    nonceFactory = randomUUID,
  } = {}) {
    super();
    if (typeof WebSocketImpl !== 'function' || typeof url !== 'string' || !url) {
      throw new TypeError('robot websocket dependencies are invalid');
    }
    this.WebSocketImpl = WebSocketImpl;
    this.url = url;
    this.nowNs = nowNs;
    if (!Number.isFinite(gripperMaxWidthM) || gripperMaxWidthM <= 0 ||
        gripperMaxWidthM > 0.080) {
      throw new TypeError('gripperMaxWidthM is invalid');
    }
    this.gripperMaxWidthM = gripperMaxWidthM;
    if (!Number.isFinite(maxStateAgeMs) || maxStateAgeMs <= 0 ||
        maxStateAgeMs > 10000) throw new TypeError('maxStateAgeMs is invalid');
    this.maxStateAgeMs = maxStateAgeMs;
    if (!Number.isFinite(maxStationaryJointSpeedDegS) ||
        maxStationaryJointSpeedDegS <= 0 || maxStationaryJointSpeedDegS > 1.0) {
      throw new TypeError('maxStationaryJointSpeedDegS is invalid');
    }
    this.maxStationaryJointSpeedDegS = maxStationaryJointSpeedDegS;
    if (typeof nonceFactory !== 'function') throw new TypeError('nonceFactory is invalid');
    this.nonceFactory = nonceFactory;
    this.stopProofMode = 'fresh_state_boundary';
    this.ws = null;
    this.connected = false;
    this.protocolReady = false;
    this.handshakeNonce = null;
    this.inFlight = null;
    this.stopInFlight = null;
    this.robotState = null;
    this.handshakeReceivedNs = null;
    this.handshakeProducerNs = null;
    this.lastStateSequence = null;
    this.lastProducerMonotonicNs = null;
  }

  connect() {
    if (this.ws) return false;
    const socket = new this.WebSocketImpl(this.url);
    this.ws = socket;
    socket.on('open', () => {
      this.connected = true;
      this.protocolReady = false;
      this.handshakeNonce = this.nonceFactory();
      if (typeof this.handshakeNonce !== 'string' || !this.handshakeNonce) {
        this._emit({ type: 'error', reason: 'capability_nonce_invalid', request_id: null });
        return;
      }
      try {
        socket.send(JSON.stringify({
          type: 'capability_request',
          schema: 'thirdhand-robot-capability-v1',
          nonce: this.handshakeNonce,
        }));
      } catch {
        this._emit({ type: 'error', reason: 'capability_request_failed', request_id: null });
      }
      this._emit({ type: 'connection', connected: true });
    });
    socket.on('message', raw => this._onMessage(raw));
    socket.on('error', error => this._emit({
      type: 'error', reason: 'robot_websocket_error', message: error.message,
      request_id: this.inFlight?.requestId ?? null,
    }));
    socket.on('close', () => {
      this.connected = false;
      this.protocolReady = false;
      this.handshakeNonce = null;
      this.handshakeReceivedNs = null;
      this.handshakeProducerNs = null;
      this.lastStateSequence = null;
      this.lastProducerMonotonicNs = null;
      this.robotState = null;
      this.ws = null;
      this.inFlight = null;
      this.stopInFlight = null;
      this._emit({ type: 'connection', connected: false });
    });
    return true;
  }

  send(command) {
    if (!command || typeof command !== 'object' || Array.isArray(command) ||
        !ALLOWED_COMMANDS.has(command.cmd) || this.protocolReady !== true || !this.ws ||
        this.ws.readyState !== this.WebSocketImpl.OPEN) return false;
    const ownsFlight = !['get_state', 'software_stop'].includes(command.cmd);
    const ownsStop = command.cmd === 'software_stop';
    if (ownsFlight) {
      if (this.inFlight !== null || typeof command.request_id !== 'string' ||
          !command.request_id) return false;
      this.inFlight = { requestId: command.request_id, command: command.cmd };
    }
    if (ownsStop) {
      if (this.stopInFlight !== null || typeof command.request_id !== 'string' ||
          !command.request_id) return false;
      this.stopInFlight = {
        requestId: command.request_id,
        command: command.cmd,
        minimumStateSequence: this.lastStateSequence,
        minimumProducerMonotonicNs: this.lastProducerMonotonicNs,
      };
    }
    try {
      this.ws.send(JSON.stringify({ ...command }));
      return true;
    } catch {
      if (ownsFlight) this.inFlight = null;
      if (ownsStop) this.stopInFlight = null;
      return false;
    }
  }

  getRobotState() {
    if (this.robotState === null) return null;
    const state = this.robotState;
    const currentNs = Number(this.nowNs());
    const localAgeMs = (currentNs - state.observedMonotonicNs) / 1_000_000;
    const sourceAgeMs = this._sourceAgeMs(currentNs, state.producerMonotonicNs);
    const stateFresh = Number.isSafeInteger(currentNs) && localAgeMs >= 0 &&
      localAgeMs <= this.maxStateAgeMs && Number.isFinite(sourceAgeMs) &&
      Math.abs(sourceAgeMs) <= this.maxStateAgeMs;
    return {
      ...state,
      stateFresh,
      flangePositionM: [...state.flangePositionM],
      flangeEulerRad: [...state.flangeEulerRad],
      jointsDeg: [...state.jointsDeg],
      velocitiesDegS: [...state.velocitiesDegS],
    };
  }

  shutdown() {
    if (!this.ws) return;
    const socket = this.ws;
    this.ws = null;
    this.inFlight = null;
    this.stopInFlight = null;
    try { socket.close(); } catch {}
  }

  _onMessage(raw) {
    let message;
    try { message = JSON.parse(raw.toString()); } catch {
      this._emit({ type: 'error', reason: 'robot_message_invalid', request_id: null });
      return;
    }
    if (message.type === 'capability_response') {
      if (this.protocolReady === true || this.handshakeNonce === null) {
        this._emit({
          type: 'error', reason: 'capability_response_unexpected', request_id: null,
        });
        return;
      }
      const expectedCommands = [...ALLOWED_COMMANDS];
      const commands = Array.isArray(message.commands) ? message.commands : [];
      const commandSet = new Set(commands);
      const units = message.state_units;
      const stream = message.state_stream;
      const receivedNs = Number(this.nowNs());
      const valid = message.schema === 'thirdhand-robot-capability-v1' &&
        message.nonce === this.handshakeNonce &&
        message.protocol_version === 'thirdhand-robot-lowlevel-v1' &&
        message.pose_frame === 'robot_flange' &&
        commands.length === expectedCommands.length &&
        expectedCommands.every(command => commandSet.has(command)) &&
        message.correlated_completions === true &&
        message.software_stop_ack === true && units?.position === 'm' &&
        message.software_stop_state_boundary === true &&
        units.orientation === 'rad' && units.joints === 'deg' &&
        units.joint_velocity === 'deg/s' && units.gripper === 'm' &&
        stream?.sequence === 'uint53' &&
        stream.producer_monotonic_ns === 'uint53' &&
        stream.strictly_increasing === true &&
        Number.isSafeInteger(message.state_sequence) && message.state_sequence >= 0 &&
        Number.isSafeInteger(message.producer_monotonic_ns) &&
        message.producer_monotonic_ns >= 0 && Number.isSafeInteger(receivedNs);
      this.protocolReady = valid;
      this.handshakeReceivedNs = valid ? receivedNs : null;
      this.handshakeProducerNs = valid ? message.producer_monotonic_ns : null;
      this.lastStateSequence = valid ? message.state_sequence : null;
      this.lastProducerMonotonicNs = valid ? message.producer_monotonic_ns : null;
      if (valid) this.handshakeNonce = null;
      this._emit({
        type: 'protocol', ready: valid,
        reason: valid ? null : 'capability_handshake_invalid',
      });
      return;
    }
    if (this.protocolReady !== true) {
      this._emit({ type: 'error', reason: 'protocol_not_ready', request_id: null });
      return;
    }
    if (message.type === 'robot_state') {
      const normalized = this._normalizeState(message);
      if (normalized === null) {
        this._emit({ type: 'error', reason: 'robot_state_invalid', request_id: null });
        return;
      }
      this.robotState = normalized;
      this._emit({ type: 'robot_state', ...this.getRobotState() });
      return;
    }
    if (message.type === 'command_status') {
      const requestId = message.request_id;
      const command = message.command;
      const expectedFlight = command === 'software_stop'
        ? this.stopInFlight : this.inFlight;
      if (typeof requestId !== 'string' || !requestId ||
          typeof command !== 'string' || !ALLOWED_COMMANDS.has(command) ||
          expectedFlight?.requestId !== requestId || expectedFlight.command !== command) {
        this._emit({
          type: 'error', reason: 'command_response_uncorrelated',
          request_id: typeof requestId === 'string' ? requestId : null,
        });
        return;
      }
      if (message.status === 'accepted') {
        this._emit({ type: 'command_accepted', command, request_id: requestId });
        return;
      }
      if (message.status === 'complete') {
        const stopBoundaryValid = command !== 'software_stop' ||
          validStopBoundary(message, expectedFlight);
        this._emit({
          type: 'command_complete',
          command,
          request_id: requestId,
          reached: message.reached === true,
          ...(vector(message.actual_joints_deg, 6)
            ? { actualJointsDeg: Object.freeze([...message.actual_joints_deg]) }
            : {}),
          actual_width_m: Number.isFinite(message.actual_width_m)
            ? message.actual_width_m
            : Number.isFinite(message.actual_position)
              ? message.actual_position * this.gripperMaxWidthM : undefined,
          robot_healthy: message.robot_healthy === true,
          stopped: message.stopped === true && stopBoundaryValid,
          applied_state_sequence: stopBoundaryValid
            ? message.applied_state_sequence : undefined,
          applied_producer_monotonic_ns: stopBoundaryValid
            ? message.applied_producer_monotonic_ns : undefined,
        });
        if (command === 'software_stop') this.stopInFlight = null;
        else if (this.inFlight?.requestId === requestId) this.inFlight = null;
        return;
      }
    }
    if (message.type === 'command_complete') {
      const expectedFlight = message.command === 'software_stop'
        ? this.stopInFlight : this.inFlight;
      if (typeof message.request_id !== 'string' || !message.request_id ||
          typeof message.command !== 'string' ||
          expectedFlight?.requestId !== message.request_id ||
          expectedFlight.command !== message.command) {
        this._emit({
          type: 'error', reason: 'command_response_uncorrelated',
          request_id: typeof message.request_id === 'string' ? message.request_id : null,
        });
        return;
      }
      const stopBoundaryValid = message.command !== 'software_stop' ||
        validStopBoundary(message, expectedFlight);
      const event = {
        type: 'command_complete',
        command: message.command,
        request_id: message.request_id,
        reached: message.reached === true,
        ...(vector(message.actual_joints_deg, 6)
          ? { actualJointsDeg: Object.freeze([...message.actual_joints_deg]) }
          : {}),
        actual_width_m: Number.isFinite(message.actual_width_m)
          ? message.actual_width_m
          : Number.isFinite(message.actual_position)
            ? message.actual_position * this.gripperMaxWidthM : undefined,
        robot_healthy: message.robot_healthy === true,
        stopped: message.stopped === true && stopBoundaryValid,
        applied_state_sequence: stopBoundaryValid
          ? message.applied_state_sequence : undefined,
        applied_producer_monotonic_ns: stopBoundaryValid
          ? message.applied_producer_monotonic_ns : undefined,
      };
      this._emit(event);
      if (message.command === 'software_stop') this.stopInFlight = null;
      else if (this.inFlight?.requestId === event.request_id) this.inFlight = null;
      return;
    }
    if (message.type === 'error') {
      const command = message.command;
      const requestId = message.request_id;
      const expectedFlight = command === 'software_stop'
        ? this.stopInFlight : this.inFlight;
      if (typeof requestId !== 'string' || !requestId ||
          typeof command !== 'string' ||
          expectedFlight?.requestId !== requestId || expectedFlight.command !== command) {
        this._emit({
          type: 'error', reason: 'command_response_uncorrelated',
          request_id: typeof requestId === 'string' ? requestId : null,
        });
        return;
      }
      this._emit({
        type: 'error',
        command,
        request_id: requestId,
        reason: message.reason ?? message.msg ?? message.message ?? 'robot_error',
      });
      if (command === 'software_stop') this.stopInFlight = null;
      else this.inFlight = null;
      return;
    }
    if (message.type === 'software_stop' || message.type === 'connection') {
      this._emit({ ...message });
    }
  }

  _normalizeState(message) {
    if (typeof message.connected !== 'boolean' || typeof message.moving !== 'boolean' ||
        !Number.isSafeInteger(message.state_sequence) || message.state_sequence < 0 ||
        !Number.isSafeInteger(message.producer_monotonic_ns) ||
        message.producer_monotonic_ns < 0 ||
        !Number.isSafeInteger(this.lastStateSequence) ||
        !Number.isSafeInteger(this.lastProducerMonotonicNs) ||
        message.state_sequence <= this.lastStateSequence ||
        message.producer_monotonic_ns <= this.lastProducerMonotonicNs ||
        message.pose_frame !== 'robot_flange' ||
        !vector(message.flange_position_m, 3) ||
        !vector(message.flange_euler_rad, 3) ||
        !vector(message.joints_deg, 6) || !vector(message.velocities_deg_s, 6)) return null;
    const gripperWidthM = Number.isFinite(message.gripper_width_m)
      ? message.gripper_width_m
      : Number.isFinite(message.gripper_position)
        ? message.gripper_position * this.gripperMaxWidthM : NaN;
    if (!Number.isFinite(gripperWidthM)) return null;
    const timestamp = Number(this.nowNs());
    if (!Number.isSafeInteger(timestamp) || timestamp < 0) return null;
    const sourceAgeMs = this._sourceAgeMs(timestamp, message.producer_monotonic_ns);
    if (!Number.isFinite(sourceAgeMs) || Math.abs(sourceAgeMs) > this.maxStateAgeMs) {
      return null;
    }
    const stationary = message.moving === false &&
      message.velocities_deg_s.every(
        value => Math.abs(value) <= this.maxStationaryJointSpeedDegS
      );
    this.lastStateSequence = message.state_sequence;
    this.lastProducerMonotonicNs = message.producer_monotonic_ns;
    return Object.freeze({
      connected: message.connected,
      moving: message.moving,
      stationary,
      stateFresh: true,
      healthy: message.healthy === true,
      poseFrame: 'robot_flange',
      flangePositionM: Object.freeze([...message.flange_position_m]),
      flangeEulerRad: Object.freeze([...message.flange_euler_rad]),
      jointsDeg: Object.freeze([...message.joints_deg]),
      velocitiesDegS: Object.freeze([...message.velocities_deg_s]),
      gripperWidthM,
      stateSequence: message.state_sequence,
      producerMonotonicNs: message.producer_monotonic_ns,
      observedMonotonicNs: timestamp,
    });
  }

  _sourceAgeMs(currentNs, producerMonotonicNs) {
    if (!Number.isSafeInteger(currentNs) ||
        !Number.isSafeInteger(producerMonotonicNs) ||
        !Number.isSafeInteger(this.handshakeReceivedNs) ||
        !Number.isSafeInteger(this.handshakeProducerNs)) return NaN;
    return ((currentNs - this.handshakeReceivedNs) -
      (producerMonotonicNs - this.handshakeProducerNs)) / 1_000_000;
  }

  _emit(event) {
    const frozen = Object.freeze(event);
    if (event.type !== 'error' || this.listenerCount('error') > 0) {
      this.emit(event.type, frozen);
    }
    this.emit('event', frozen);
  }
}

module.exports = { ALLOWED_COMMANDS, RobotWebSocketClient };
