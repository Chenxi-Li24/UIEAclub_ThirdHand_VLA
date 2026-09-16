'use strict';

const { EventEmitter } = require('events');
const DefaultWebSocket = require('ws');
const { MANUAL_SKILL, normalizeMultiJointMoves } = require('./manual-joint-control');
const {
  DIRECTIONAL_MAPPING,
  DIRECTIONAL_SKILL,
  normalizeDirectionalMoves,
} = require('./directional-joint-control');

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);
const MANUAL_COMMANDS = new Set([
  'connect',
  'disconnect',
  'servo',
  'preset',
  'gripper',
  'status',
]);

function finiteArray(values, length) {
  if (!Array.isArray(values) || values.length !== length) return null;
  const numbers = values.map(Number);
  return numbers.every(Number.isFinite) ? numbers : null;
}

function normalizeEndpoint(value) {
  if (!value) return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error('LANGUAGE_UPSTREAM_WS must be a valid ws:// URL');
  }
  if (url.protocol !== 'ws:' || !LOOPBACK_HOSTS.has(url.hostname) || url.pathname !== '/ws') {
    throw new Error('LANGUAGE_UPSTREAM_WS must use ws://127.0.0.1:<port>/ws');
  }
  return url.toString();
}

function directionalAuthorizationMatches(authorization, currentDeg, targetDeg) {
  if (!authorization || typeof authorization !== 'object' || Array.isArray(authorization)) return false;
  if (authorization.skill !== DIRECTIONAL_SKILL) return false;
  const keys = Object.keys(authorization).sort().join(',');
  const params = keys === 'moves,skill'
    ? { moves: authorization.moves }
    : keys === 'action,deltaDeg,skill'
      ? { action: authorization.action, deltaDeg: authorization.deltaDeg }
      : null;
  const normalized = normalizeDirectionalMoves(params);
  if (!normalized.ok) return false;
  const expected = [...currentDeg];
  for (const move of normalized.moves) {
    for (const [index, sign] of DIRECTIONAL_MAPPING[move.action]) {
      expected[index] += sign * move.deltaDeg;
    }
  }
  return expected.every((value, index) => Math.abs(value - targetDeg[index]) <= 0.01);
}

function manualJointAuthorizationMatches(authorization, currentDeg, targetDeg) {
  if (!authorization || typeof authorization !== 'object' || Array.isArray(authorization)) return false;
  if (Object.keys(authorization).sort().join(',') !== 'action,moves,skill' ||
      authorization.skill !== MANUAL_SKILL || authorization.action !== 'joint.multi') return false;
  const normalized = normalizeMultiJointMoves(authorization.moves);
  if (!normalized.ok) return false;
  const expected = [...currentDeg];
  for (const move of normalized.moves) {
    const index = move.joint - 1;
    expected[index] = 'targetDeg' in move ? move.targetDeg : currentDeg[index] + move.deltaDeg;
  }
  return expected.every((value, index) => Math.abs(value - targetDeg[index]) <= 0.01);
}

class LanguageUpstreamBridge extends EventEmitter {
  constructor(options = {}) {
    super();
    this.endpoint = normalizeEndpoint(options.endpoint);
    this.WebSocketImpl = options.WebSocketImpl || DefaultWebSocket;
    this.now = options.now || Date.now;
    this.schedule = options.schedule || setTimeout;
    this.cancelSchedule = options.cancelSchedule || clearTimeout;
    this.stateMaxAgeMs = Number(options.stateMaxAgeMs ?? 500);
    const configuredMaxDeltaDeg = Number(options.maxDeltaDeg);
    this.maxDeltaDeg = Number.isFinite(configuredMaxDeltaDeg) && configuredMaxDeltaDeg > 0
      ? configuredMaxDeltaDeg
      : null;
    this.maxSpeedScale = Number(options.maxSpeedScale ?? 0.05);
    this.reconnectDelayMs = Number(options.reconnectDelayMs ?? 1000);
    this.acceptTimeoutMs = Number(options.acceptTimeoutMs ?? 1500);
    this.probeOnOpen = options.probeOnOpen !== false;
    this.socket = null;
    this.reconnectTimer = null;
    this.stopping = false;
    this.connected = false;
    this.simulated = null;
    this.upstreamInterface = null;
    this.upstreamDryRun = null;
    this.upstreamSpeedScale = null;
    this.upstreamPresets = {};
    this.latestJointsDeg = null;
    this.latestGripperPosition = null;
    this.latestRobotStateName = null;
    this.latestRobotStateAtMs = null;
    this.motionActive = false;
    this.externalCommandActive = false;
    this.inFlight = null;
  }

  start() {
    if (!this.endpoint || this.socket) return false;
    this.stopping = false;
    this._connect();
    return true;
  }

  shutdown() {
    this.stopping = true;
    if (this.reconnectTimer) this.cancelSchedule(this.reconnectTimer);
    this.reconnectTimer = null;
    if (this.inFlight?.acceptTimer) this.cancelSchedule(this.inFlight.acceptTimer);
    this.inFlight = null;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < 2) socket.close();
  }

  publicStatus() {
    const state = this.getRobotState();
    return {
      backend: 'formal-3000-upstream',
      configured: Boolean(this.endpoint),
      connected: state.connected,
      stateFresh: state.stateFresh,
      ageMs: state.ageMs,
      stateName: state.stateName,
      motionActive: state.motionActive,
      joints: state.jointsDeg,
      gripperPosition: state.gripperPosition,
      speedScale: this.upstreamSpeedScale,
      simulated: this.simulated,
    };
  }

  manualConnectionInfo() {
    return {
      mode: 'startouch-upstream',
      host: '127.0.0.1',
      interface: this.upstreamInterface || 'can0',
      connected: this.connected && this.simulated === false,
      ready: this._socketReady(),
      simulated: this.simulated === true,
      dryRun: this.upstreamDryRun === true,
    };
  }

  getRobotState() {
    const ageMs = this.latestRobotStateAtMs === null
      ? null
      : Math.max(0, this.now() - this.latestRobotStateAtMs);
    const stateFresh = ageMs !== null && ageMs <= this.stateMaxAgeMs;
    const speedSafe = Number.isFinite(this.upstreamSpeedScale) &&
      this.upstreamSpeedScale <= this.maxSpeedScale + 1e-9;
    return {
      simulated: this.simulated === true,
      connected: this.connected && this.simulated === false && speedSafe,
      stateFresh,
      ageMs,
      stateName: this.latestRobotStateName,
      motionActive: this.motionActive || this.externalCommandActive || Boolean(this.inFlight),
      activeViewActive: false,
      graspActive: false,
      jointsDeg: this.latestJointsDeg === null ? null : [...this.latestJointsDeg],
      gripperPosition: this.latestGripperPosition,
    };
  }

  getPreset(name) {
    const preset = this.upstreamPresets[name];
    return Array.isArray(preset) ? [...preset] : null;
  }

  send(command) {
    if (!command || typeof command !== 'object') return false;
    if (command.cmd === 'move_joint') return this._sendJoint(command);
    if (command.cmd === 'preset_home') return this._sendHome(command);
    if (command.cmd === 'gripper') return this._sendGripper(command);
    return false;
  }

  sendManual(command) {
    if (!command || typeof command !== 'object' || !MANUAL_COMMANDS.has(command.cmd)) {
      return false;
    }
    if (!this._socketReady()) return false;
    this._sendJson(command);
    return true;
  }

  softwareStop() {
    if (!this._socketReady() || !this.connected) return false;
    this._sendJson({ cmd: 'software_stop' });
    return true;
  }

  _connect() {
    if (this.stopping || !this.endpoint || this.socket) return;
    const socket = new this.WebSocketImpl(this.endpoint);
    this.socket = socket;
    socket.on('open', () => {
      if (this.socket !== socket) return;
      if (this.probeOnOpen) this._sendJson({ cmd: 'status' });
      this._emitStatus();
    });
    socket.on('message', data => {
      if (this.socket !== socket) return;
      let message;
      try {
        message = JSON.parse(data.toString());
      } catch {
        this.emit('log', { level: 'warning', message: 'Invalid JSON from formal 3000 upstream' });
        return;
      }
      this._handleMessage(message);
    });
    socket.on('error', error => {
      if (this.socket !== socket) return;
      this.emit('log', { level: 'warning', message: `Formal 3000 upstream error: ${error.message}` });
    });
    socket.on('close', () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this._resetConnection('formal_3000_ws_closed');
      if (!this.stopping) this._scheduleReconnect();
    });
  }

  _scheduleReconnect() {
    if (this.reconnectTimer || this.stopping) return;
    this.reconnectTimer = this.schedule(() => {
      this.reconnectTimer = null;
      this._connect();
    }, this.reconnectDelayMs);
  }

  _resetConnection(reason) {
    this.connected = false;
    this.latestJointsDeg = null;
    this.latestRobotStateName = null;
    this.latestRobotStateAtMs = null;
    this.motionActive = false;
    this.externalCommandActive = false;
    if (this.inFlight?.acceptTimer) this.cancelSchedule(this.inFlight.acceptTimer);
    this.inFlight = null;
    const event = { type: 'connection', connected: false, reason };
    this.emit('message', event);
    this._emitStatus();
  }

  _handleMessage(message) {
    if (!message || typeof message !== 'object') return;
    this.emit('upstream_message', message);
    if (message.type === 'config') {
      this.connected = message.connection?.connected === true;
      this.simulated = message.connection?.simulated === true;
      this.upstreamInterface = message.connection?.interface || this.upstreamInterface;
      this.upstreamDryRun = message.connection?.dryRun === true;
      this.upstreamSpeedScale = Number(message.motion?.speedScale);
      const home = finiteArray(message.presets?.home, 6);
      this.upstreamPresets = home ? { home } : {};
      if (!this.probeOnOpen && this.connected && this.latestRobotStateAtMs === null) {
        this._sendJson({ cmd: 'status' });
      }
      this._emitStatus();
      return;
    }
    if (message.type === 'connection') {
      this.connected = message.connected === true;
      this.upstreamInterface = message.interface || this.upstreamInterface;
      if (!this.probeOnOpen && this.connected && this.latestRobotStateAtMs === null) {
        this._sendJson({ cmd: 'status' });
      }
      if (!this.connected) {
        this.latestJointsDeg = null;
        this.latestRobotStateAtMs = null;
        this.latestRobotStateName = null;
        this.motionActive = false;
      }
      this.emit('message', { ...message, type: 'connection' });
      this._emitStatus();
      return;
    }
    if (message.type === 'robot_state') {
      const joints = finiteArray(message.joints, 6);
      if (!joints) return;
      this.latestJointsDeg = joints;
      this.latestGripperPosition = Number.isFinite(Number(message.gripperPosition))
        ? Number(message.gripperPosition)
        : this.latestGripperPosition;
      this.latestRobotStateName = message.stateName || this.latestRobotStateName;
      this.latestRobotStateAtMs = this.now();
      this.emit('message', {
        type: 'robot_state',
        joints: [...joints],
        stateName: this.latestRobotStateName,
        connected: this.connected,
        observedAtMs: this.latestRobotStateAtMs,
        ts: this.latestRobotStateAtMs,
      });
      this._completeCorrelationIfVerified();
      this._emitStatus();
      return;
    }
    if (message.type === 'motion_state') {
      this.motionActive = message.stateName === 'MOVING';
      if (message.stateName === 'IDLE') this.externalCommandActive = false;
      this._emitStatus();
      return;
    }
    if (message.type === 'command_status') {
      this._handleCommandStatus(message);
      return;
    }
    if (message.type === 'error') {
      this._handleError(message);
      return;
    }
    if (message.type === 'software_stop') {
      if (message.complete === true) {
        this.emit('message', { type: 'software_stop_complete', ts: message.ts || this.now() });
      } else if (message.complete === false && message.depowered === false) {
        this.emit('message', {
          type: 'software_stop_timeout',
          message: message.msg || 'Formal 3000 software stop was not verified',
        });
      }
      return;
    }
  }

  _sendJoint(command) {
    const state = this.getRobotState();
    const targetRad = finiteArray(command.joints_rad, 6);
    if (!this._canStart(state) || !targetRad) return false;
    const targetDeg = targetRad.map(value => value * 180 / Math.PI);
    const deltas = targetDeg.map((value, index) => Math.abs(value - state.jointsDeg[index]));
    const changed = deltas.filter(delta => delta > 0.01);
    const directionalAuthorization = command.directional_authorization;
    const manualAuthorization = command.manual_joint_authorization;
    if (directionalAuthorization && manualAuthorization) return false;
    if (directionalAuthorization) {
      if (!directionalAuthorizationMatches(directionalAuthorization, state.jointsDeg, targetDeg)) return false;
    } else if (manualAuthorization) {
      if (changed.length === 0 || !manualJointAuthorizationMatches(
        manualAuthorization, state.jointsDeg, targetDeg
      )) return false;
    } else if (changed.length !== 1) {
      return false;
    }
    if (this.maxDeltaDeg !== null && changed.some(delta => delta > this.maxDeltaDeg + 1e-9)) {
      return false;
    }
    const localRequestId = command.request_id;
    if (typeof localRequestId !== 'string' || !localRequestId) return false;
    this._beginCorrelation({
      kind: 'joint',
      command: 'move_joint',
      localRequestId,
      targetDeg,
      sentAtMs: this.now(),
    });
    this._sendJson({ cmd: 'servo', joints: targetDeg });
    return true;
  }

  _sendHome(command) {
    const state = this.getRobotState();
    const targetDeg = this.getPreset('home');
    if (!this._canStart(state) || !targetDeg) return false;
    const localRequestId = command.request_id;
    if (typeof localRequestId !== 'string' || !localRequestId) return false;
    this._beginCorrelation({
      kind: 'joint',
      command: 'move_joint',
      localRequestId,
      targetDeg,
      sentAtMs: this.now(),
    });
    this._sendJson({ cmd: 'preset', name: 'home' });
    return true;
  }

  _sendGripper(command) {
    const state = this.getRobotState();
    const position = Number(command.position);
    if (!this._canStart(state) || !Number.isFinite(position) || position < 0 || position > 1) return false;
    const localRequestId = command.request_id;
    if (typeof localRequestId !== 'string' || !localRequestId) return false;
    this._beginCorrelation({
      kind: 'gripper',
      command: 'gripper',
      localRequestId,
      targetPosition: position,
      sentAtMs: this.now(),
    });
    this._sendJson({ cmd: 'gripper', position });
    return true;
  }

  _canStart(state) {
    return Boolean(
      this._socketReady() && state.connected && state.stateFresh &&
      state.stateName === 'IDLE' && !state.motionActive &&
      Array.isArray(state.jointsDeg) && !this.inFlight
    );
  }

  _beginCorrelation(data) {
    this.inFlight = {
      ...data,
      upstreamRequestId: undefined,
      completeReceived: false,
      acceptTimer: this.schedule(() => {
        if (!this.inFlight || this.inFlight.localRequestId !== data.localRequestId ||
            this.inFlight.upstreamRequestId !== undefined) return;
        this._failInFlight('Formal 3000 did not acknowledge the Language command');
      }, this.acceptTimeoutMs),
    };
  }

  _handleCommandStatus(message) {
    const active = this.inFlight;
    if (!active) {
      if (message.status === 'accepted') this.externalCommandActive = true;
      if (message.status === 'complete') this.externalCommandActive = false;
      this._emitStatus();
      return;
    }
    const commandMatches = message.command === active.command;
    if (message.status === 'accepted') {
      if (!commandMatches || active.upstreamRequestId !== undefined) {
        this._failInFlight('Another command overlapped the Language command; result is uncertain');
        return;
      }
      active.upstreamRequestId = message.request_id ?? null;
      if (active.acceptTimer) this.cancelSchedule(active.acceptTimer);
      active.acceptTimer = null;
      this.emit('message', {
        type: 'command_accepted',
        command: active.command,
        request_id: active.localRequestId,
      });
      return;
    }
    if (message.status !== 'complete') return;
    if (!commandMatches || active.upstreamRequestId === undefined ||
        (message.request_id ?? null) !== active.upstreamRequestId) {
      this._failInFlight('Formal 3000 completion did not match the Language command');
      return;
    }
    active.completeReceived = true;
    active.completedAtMs = this.now();
    this.emit('message', {
      ...message,
      type: 'command_complete',
      request_id: active.localRequestId,
    });
    if (active.kind === 'gripper') this.inFlight = null;
  }

  _handleError(message) {
    const active = this.inFlight;
    if (!active) return;
    const upstreamId = message.requestId ?? null;
    if (active.upstreamRequestId === undefined || upstreamId === active.upstreamRequestId) {
      this._failInFlight(message.msg || 'Formal 3000 rejected the Language command');
    }
  }

  _completeCorrelationIfVerified() {
    const active = this.inFlight;
    if (!active || active.kind !== 'joint' || !active.completeReceived) return;
    if (this.latestRobotStateAtMs < active.completedAtMs || this.latestRobotStateName !== 'IDLE') return;
    const matches = active.targetDeg.every(
      (value, index) => Math.abs(value - this.latestJointsDeg[index]) <= 1
    );
    if (matches) this.inFlight = null;
  }

  _failInFlight(message) {
    const active = this.inFlight;
    if (!active) return;
    if (active.acceptTimer) this.cancelSchedule(active.acceptTimer);
    this.inFlight = null;
    this.emit('message', {
      type: 'error',
      message,
      request_id: active.localRequestId,
    });
    this._emitStatus();
  }

  _sendJson(message) {
    this.socket.send(JSON.stringify(message));
  }

  _socketReady() {
    const open = this.WebSocketImpl.OPEN ?? DefaultWebSocket.OPEN;
    return Boolean(this.socket && this.socket.readyState === open);
  }

  _emitStatus() {
    this.emit('status', this.publicStatus());
  }
}

module.exports = {
  LanguageUpstreamBridge,
  normalizeEndpoint,
};
