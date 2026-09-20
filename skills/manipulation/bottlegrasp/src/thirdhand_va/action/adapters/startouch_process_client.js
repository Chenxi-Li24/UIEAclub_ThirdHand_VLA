'use strict';

const childProcess = require('node:child_process');
const crypto = require('node:crypto');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;
const WIRE_COMMANDS = Object.freeze([
  'connect', 'disconnect', 'get_state', 'gripper',
  'move_joint', 'move_l', 'software_stop',
]);
const PUBLIC_COMMANDS = Object.freeze(new Set([
  'get_state', 'gripper', 'move_joint', 'move_l', 'preset', 'software_stop',
]));
const STATE_UNITS = Object.freeze({
  gripper: 'm',
  joint_velocity: 'deg/s',
  joints: 'deg',
  orientation: 'rad',
  position: 'm',
});
// Reuse the 2 deg/s idle-noise envelope validated by TH-Fanxy on this
// Startouch tracker. Python assigns the wire `moving` bit with the same limit.
const STATIONARY_MAX_VELOCITY_DEG_S = 2.0;

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonicalize(value[key])])
    );
  }
  return value;
}

function contentId(bytes) {
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function runtimeConfigId(settings) {
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
    throw new TypeError('runtimeSettings must be an object');
  }
  return contentId(Buffer.from(JSON.stringify(canonicalize(settings))));
}

function bridgeContentId(bridgePath) {
  const directory = path.dirname(bridgePath);
  const hash = crypto.createHash('sha256');
  for (const name of [
    'protocol.py', 'vendor_runtime.py', 'backends.py', 'startouch_bridge.py',
  ]) {
    hash.update(name);
    hash.update(Buffer.from([0]));
    hash.update(fs.readFileSync(path.join(directory, name)));
    hash.update(Buffer.from([0]));
  }
  return `sha256:${hash.digest('hex')}`;
}

function vector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function positive(value, maximum) {
  return Number.isFinite(value) && value > 0 && value <= maximum;
}

function sameKeysAndValues(actual, expected) {
  if (!actual || typeof actual !== 'object' || Array.isArray(actual)) return false;
  const actualKeys = Object.keys(actual).sort();
  const expectedKeys = Object.keys(expected).sort();
  return actualKeys.length === expectedKeys.length &&
    actualKeys.every((key, index) => key === expectedKeys[index] && actual[key] === expected[key]);
}

class StartouchProcessClient extends EventEmitter {
  constructor({
    pythonExecutable,
    bridgePath,
    bridgeArgs = [],
    runtimeSettings,
    childEnvironment = {},
    presets = {},
    jointMaxSpeedsDegS = [300, 300, 300, 1000, 1000, 1000],
    speedScale = 0.05,
    spawnImpl = childProcess.spawn,
    nowNs = process.hrtime.bigint,
    maxStateAgeMs = 250,
  } = {}) {
    super();
    if (typeof pythonExecutable !== 'string' || !pythonExecutable ||
        typeof bridgePath !== 'string' || !bridgePath ||
        !Array.isArray(bridgeArgs) || !bridgeArgs.every(value => typeof value === 'string') ||
        !childEnvironment || typeof childEnvironment !== 'object' ||
        Array.isArray(childEnvironment) ||
        Object.values(childEnvironment).some(value => typeof value !== 'string') ||
        typeof spawnImpl !== 'function' || typeof nowNs !== 'function' ||
        !positive(maxStateAgeMs, 10000) || !vector(jointMaxSpeedsDegS, 6) ||
        jointMaxSpeedsDegS.some(value => value <= 0) ||
        !Number.isFinite(speedScale) || speedScale <= 0 || speedScale > 0.10 ||
        !presets || typeof presets !== 'object' || Array.isArray(presets)) {
      throw new TypeError('startouch process dependencies are invalid');
    }
    const normalizedPresets = {};
    for (const [name, joints] of Object.entries(presets)) {
      if (!name || !vector(joints, 6)) throw new TypeError('robot preset is invalid');
      normalizedPresets[name] = Object.freeze([...joints]);
    }
    this.pythonExecutable = pythonExecutable;
    this.bridgePath = path.resolve(bridgePath);
    this.bridgeArgs = [...bridgeArgs];
    this.runtimeSettings = Object.freeze(canonicalize(runtimeSettings));
    this.childEnvironment = Object.freeze({ ...childEnvironment });
    this.expectedBridgeContentId = bridgeContentId(this.bridgePath);
    this.expectedRuntimeConfigId = runtimeConfigId(this.runtimeSettings);
    this.presets = Object.freeze(normalizedPresets);
    this.jointMaxSpeedsDegS = Object.freeze([...jointMaxSpeedsDegS]);
    this.speedScale = speedScale;
    this.spawnImpl = spawnImpl;
    this.nowNs = nowNs;
    this.maxStateAgeMs = maxStateAgeMs;
    this.stopProofMode = 'cleanup_ack_only';
    this.child = null;
    this.connected = false;
    this.protocolReady = false;
    this.robotState = null;
    this.inFlight = null;
    this.stopInFlight = null;
    this.stdoutBuffer = '';
    this.stderrBuffer = '';
    this.shutdownRequested = false;
    this.firstStateObservedNs = null;
    this.firstStateProducerNs = null;
    this.lastStateSequence = null;
    this.lastProducerMonotonicNs = null;
  }

  connect() {
    if (this.child !== null) return false;
    this.shutdownRequested = false;
    let child;
    try {
      child = this.spawnImpl(
        this.pythonExecutable,
        [this.bridgePath, ...this.bridgeArgs],
        {
          cwd: path.resolve(path.dirname(this.bridgePath), '../..'),
          env: {
            ...process.env,
            ...this.childEnvironment,
            PYTHONUNBUFFERED: '1',
          },
          stdio: ['pipe', 'pipe', 'pipe'],
        },
      );
    } catch (error) {
      this._emit({
        type: 'error', reason: 'robot_process_spawn_failed',
        message: error.message, request_id: null,
      });
      return false;
    }
    this.child = child;
    child.stdout.on('data', chunk => this._onStdout(chunk));
    child.stderr.on('data', chunk => { this.stderrBuffer += chunk.toString('utf8'); });
    child.on('error', error => this._emit({
      type: 'error', reason: 'robot_process_error', message: error.message,
      request_id: this.inFlight?.requestId ?? this.stopInFlight?.requestId ?? null,
    }));
    child.on('close', (code, signal) => this._onClose(code, signal));
    return true;
  }

  send(command) {
    if (!command || typeof command !== 'object' || Array.isArray(command) ||
        !PUBLIC_COMMANDS.has(command.cmd) || this.protocolReady !== true ||
        !this.child?.stdin?.writable) return false;
    const requestId = command.request_id;
    if (typeof requestId !== 'string' || !requestId || requestId.length > 128) return false;
    const isStop = command.cmd === 'software_stop';
    const ownsFlight = command.cmd !== 'get_state' && !isStop;
    if ((ownsFlight && this.inFlight !== null) || (isStop && this.stopInFlight !== null)) {
      return false;
    }
    const wire = this._wireCommand(command);
    if (wire === null) return false;
    const flight = {
      requestId,
      publicCommand: command.cmd,
      wireCommand: wire.cmd,
    };
    if (ownsFlight) this.inFlight = flight;
    if (isStop) this.stopInFlight = flight;
    try {
      this.child.stdin.write(`${JSON.stringify(wire)}\n`);
      return true;
    } catch {
      if (ownsFlight) this.inFlight = null;
      if (isStop) this.stopInFlight = null;
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
    return Object.freeze({
      ...state,
      stateFresh,
      flangePositionM: Object.freeze([...state.flangePositionM]),
      flangeEulerRad: Object.freeze([...state.flangeEulerRad]),
      jointsDeg: Object.freeze([...state.jointsDeg]),
      velocitiesDegS: Object.freeze([...state.velocitiesDegS]),
    });
  }

  shutdown() {
    if (this.child === null) return;
    this.shutdownRequested = true;
    const child = this.child;
    try { child.stdin.end(); } catch {}
    const timer = setTimeout(() => {
      if (this.child === child) {
        try { child.kill('SIGTERM'); } catch {}
      }
    }, 500);
    timer.unref?.();
  }

  _wireCommand(command) {
    const source = typeof command.source === 'string' && command.source
      ? command.source : undefined;
    if (command.cmd === 'move_l') {
      if (!vector(command.position, 3) || !vector(command.euler, 3) ||
          !positive(command.time_sec, 30.0)) return null;
      return {
        cmd: 'move_l', request_id: command.request_id,
        flange_position_m: [...command.position],
        flange_euler_rad: [...command.euler],
        duration_sec: command.time_sec,
        ...(source === undefined ? {} : { source }),
      };
    }
    if (command.cmd === 'move_joint') {
      if (!vector(command.joints_rad, 6) || !positive(command.time_sec, 30.0)) return null;
      return {
        cmd: 'move_joint', request_id: command.request_id,
        joints_rad: [...command.joints_rad], duration_sec: command.time_sec,
        ...(source === undefined ? {} : { source }),
      };
    }
    if (command.cmd === 'preset') {
      const target = this.presets[command.name];
      const state = this.getRobotState();
      if (!target || !state || !vector(state.jointsDeg, 6)) return null;
      const rawDuration = Math.max(...target.map((value, index) =>
        Math.abs(value - state.jointsDeg[index]) /
          (this.jointMaxSpeedsDegS[index] * this.speedScale)
      ));
      const duration = Math.min(30.0, Math.max(0.5, rawDuration));
      return {
        cmd: 'move_joint', request_id: command.request_id,
        joints_rad: target.map(value => value * Math.PI / 180),
        duration_sec: Number(duration.toFixed(3)),
        ...(source === undefined ? {} : { source }),
      };
    }
    if (command.cmd === 'gripper') {
      if (!Number.isFinite(command.position) || command.position < 0 ||
          command.position > 1) return null;
      return {
        cmd: 'gripper', request_id: command.request_id, position: command.position,
        ...(source === undefined ? {} : { source }),
      };
    }
    if (command.cmd === 'software_stop') {
      const reason = typeof command.reason === 'string' && command.reason
        ? command.reason : undefined;
      return {
        cmd: 'software_stop', request_id: command.request_id,
        ...(source === undefined ? {} : { source }),
        ...(reason === undefined ? {} : { reason }),
      };
    }
    if (command.cmd === 'get_state') {
      return { cmd: 'get_state', request_id: command.request_id };
    }
    return null;
  }

  _onStdout(chunk) {
    this.stdoutBuffer += chunk.toString('utf8');
    while (true) {
      const newline = this.stdoutBuffer.indexOf('\n');
      if (newline < 0) return;
      const line = this.stdoutBuffer.slice(0, newline).trim();
      this.stdoutBuffer = this.stdoutBuffer.slice(newline + 1);
      if (!line) continue;
      let message;
      try { message = JSON.parse(line); } catch {
        this._emit({ type: 'error', reason: 'robot_message_invalid', request_id: null });
        continue;
      }
      this._onMessage(message);
    }
  }

  _onMessage(message) {
    if (message?.type === 'bridge_ready') {
      const ready = this._validReady(message);
      this.protocolReady = ready;
      this.connected = ready;
      this._emit({
        type: 'protocol', ready,
        reason: ready ? null : 'capability_handshake_invalid',
      });
      if (ready) this._emit({ type: 'connection', connected: true });
      return;
    }
    if (this.protocolReady !== true) {
      this._emit({ type: 'error', reason: 'protocol_not_ready', request_id: null });
      return;
    }
    if (message.type === 'robot_state') {
      const state = this._normalizeState(message);
      if (state === null) {
        this._emit({ type: 'error', reason: 'robot_state_invalid', request_id: null });
        return;
      }
      this.robotState = state;
      this._emit({ type: 'robot_state', ...this.getRobotState() });
      return;
    }
    if (['command_accepted', 'command_complete', 'error'].includes(message.type)) {
      this._onCommandEvent(message);
    }
  }

  _validReady(message) {
    return message.schema === 'thirdhand-startouch-bridge-v1' &&
      message.protocol_version === 'thirdhand-robot-lowlevel-v1' &&
      Array.isArray(message.commands) &&
      message.commands.length === WIRE_COMMANDS.length &&
      WIRE_COMMANDS.every(command => message.commands.includes(command)) &&
      message.correlated_completions === true &&
      message.pose_frame === 'robot_flange' &&
      message.software_stop_ack === true &&
      message.stop_proof_mode === 'cleanup_ack_only' &&
      sameKeysAndValues(message.state_units, STATE_UNITS) &&
      message.state_stream?.sequence === 'uint53' &&
      message.state_stream?.producer_monotonic_ns === 'uint53' &&
      message.state_stream?.strictly_increasing === true &&
      SHA256_ID.test(message.bridge_content_id || '') &&
      message.bridge_content_id === this.expectedBridgeContentId &&
      SHA256_ID.test(message.runtime_config_id || '') &&
      message.runtime_config_id === this.expectedRuntimeConfigId &&
      this._validRuntimeIdentity(message.runtime_identity);
  }

  _validRuntimeIdentity(identity) {
    if (!identity || typeof identity !== 'object' || Array.isArray(identity) ||
        !Array.isArray(identity.startup_feedback_ids)) return false;
    if (this.runtimeSettings.backend === 'simulate') {
      return identity.runtime_manifest_id === 'simulation' &&
        identity.safety_config_sha256 === 'simulation' &&
        identity.safety_profile_id === 'simulation' &&
        identity.startup_feedback_ids.length === 0;
    }
    return this.runtimeSettings.backend === 'startouch_sdk' &&
      identity.runtime_manifest_id === this.runtimeSettings.runtime_manifest_id &&
      identity.safety_config_sha256 === this.runtimeSettings.safety_config_sha256 &&
      identity.safety_profile_id === this.runtimeSettings.safety_profile_id &&
      identity.startup_feedback_ids.length === 7 &&
      identity.startup_feedback_ids.every(
        (value, index) => value === 0x11 + index
      );
  }

  _normalizeState(message) {
    if (message.pose_frame !== 'robot_flange' ||
        typeof message.connected !== 'boolean' || typeof message.healthy !== 'boolean' ||
        typeof message.moving !== 'boolean' ||
        !vector(message.flange_position_m, 3) || !vector(message.flange_euler_rad, 3) ||
        !vector(message.joints_deg, 6) || !vector(message.velocities_deg_s, 6) ||
        !Number.isFinite(message.gripper_width_m) ||
        !Number.isSafeInteger(message.state_sequence) || message.state_sequence <= 0 ||
        !Number.isSafeInteger(message.producer_monotonic_ns) ||
        message.producer_monotonic_ns <= 0 ||
        (this.lastStateSequence !== null &&
          message.state_sequence <= this.lastStateSequence) ||
        (this.lastProducerMonotonicNs !== null &&
          message.producer_monotonic_ns <= this.lastProducerMonotonicNs)) return null;
    const observedNs = Number(this.nowNs());
    if (!Number.isSafeInteger(observedNs) || observedNs < 0) return null;
    if (this.firstStateObservedNs === null) {
      this.firstStateObservedNs = observedNs;
      this.firstStateProducerNs = message.producer_monotonic_ns;
    }
    this.lastStateSequence = message.state_sequence;
    this.lastProducerMonotonicNs = message.producer_monotonic_ns;
    const stationary = message.moving === false &&
      message.velocities_deg_s.every(
        value => Math.abs(value) <= STATIONARY_MAX_VELOCITY_DEG_S
      );
    return Object.freeze({
      connected: message.connected,
      healthy: message.healthy,
      moving: message.moving,
      stationary,
      stateFresh: true,
      poseFrame: 'robot_flange',
      flangePositionM: Object.freeze([...message.flange_position_m]),
      flangeEulerRad: Object.freeze([...message.flange_euler_rad]),
      jointsDeg: Object.freeze([...message.joints_deg]),
      velocitiesDegS: Object.freeze([...message.velocities_deg_s]),
      gripperWidthM: message.gripper_width_m,
      stateSequence: message.state_sequence,
      producerMonotonicNs: message.producer_monotonic_ns,
      observedMonotonicNs: observedNs,
    });
  }

  _onCommandEvent(message) {
    const expected = message.command === 'software_stop'
      ? this.stopInFlight : this.inFlight;
    if (!expected || expected.requestId !== message.request_id ||
        expected.wireCommand !== message.command) {
      this._emit({
        type: 'error', reason: 'command_response_uncorrelated',
        request_id: typeof message.request_id === 'string' ? message.request_id : null,
      });
      return;
    }
    const command = expected.publicCommand;
    if (message.type === 'command_accepted') {
      this._emit({ type: 'command_accepted', command, request_id: message.request_id });
      return;
    }
    if (message.type === 'error') {
      this._emit({
        type: 'error', command, request_id: message.request_id,
        reason: message.reason || 'robot_error',
      });
    } else {
      const cleanupAcknowledged = command === 'software_stop' &&
        message.cleanup_acknowledged === true &&
        ['simulation', 'vendor_cleanup_returned'].includes(
          message.cleanup_confirmation_mode
        ) && message.control_released === true &&
        message.depower_independently_confirmed === false;
      const stopProved = false;
      this._emit({
        type: 'command_complete',
        command,
        request_id: message.request_id,
        reached: message.reached === true,
        actualFlangePositionM: vector(message.actual_flange_position_m, 3)
          ? Object.freeze([...message.actual_flange_position_m]) : undefined,
        actualFlangeEulerRad: vector(message.actual_flange_euler_rad, 3)
          ? Object.freeze([...message.actual_flange_euler_rad]) : undefined,
        ...(vector(message.actual_joints_deg, 6)
          ? { actualJointsDeg: Object.freeze([...message.actual_joints_deg]) }
          : {}),
        actual_width_m: Number.isFinite(message.actual_width_m)
          ? message.actual_width_m : undefined,
        robot_healthy: message.robot_healthy === true,
        stopped: stopProved,
        depowered: stopProved,
        ...(command === 'software_stop' ? {
          cleanupAcknowledged,
          cleanupConfirmationMode: cleanupAcknowledged
            ? message.cleanup_confirmation_mode : undefined,
          controlReleased: cleanupAcknowledged,
          depowerIndependentlyConfirmed: false,
        } : {}),
        applied_state_sequence: cleanupAcknowledged &&
          Number.isSafeInteger(message.applied_state_sequence)
          ? message.applied_state_sequence : undefined,
        applied_producer_monotonic_ns: cleanupAcknowledged &&
          Number.isSafeInteger(message.applied_producer_monotonic_ns)
          ? message.applied_producer_monotonic_ns : undefined,
      });
    }
    if (command === 'software_stop') this.stopInFlight = null;
    else this.inFlight = null;
  }

  _sourceAgeMs(currentNs, producerNs) {
    if (!Number.isSafeInteger(currentNs) || !Number.isSafeInteger(producerNs) ||
        !Number.isSafeInteger(this.firstStateObservedNs) ||
        !Number.isSafeInteger(this.firstStateProducerNs)) return NaN;
    return ((currentNs - this.firstStateObservedNs) -
      (producerNs - this.firstStateProducerNs)) / 1_000_000;
  }

  _onClose(code, signal) {
    const wasExpected = this.shutdownRequested;
    this.child = null;
    this.connected = false;
    this.protocolReady = false;
    this.robotState = null;
    this.inFlight = null;
    this.stopInFlight = null;
    this._emit({ type: 'connection', connected: false, code, signal });
    if (!wasExpected) {
      this._emit({
        type: 'error', reason: 'robot_process_exited', request_id: null,
        stderr: this.stderrBuffer.trim(),
      });
    }
  }

  _emit(event) {
    const frozen = Object.freeze(event);
    if (event.type !== 'error' || this.listenerCount('error') > 0) {
      this.emit(event.type, frozen);
    }
    this.emit('event', frozen);
  }
}

module.exports = {
  StartouchProcessClient,
  bridgeContentId,
  runtimeConfigId,
};
