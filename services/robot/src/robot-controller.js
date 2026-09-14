'use strict';

const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');
const { StartouchBridge } = require('./startouch-bridge');
const { createContractValidator } = require('../../../platform/contracts/src/validator');
const {
  DEFAULT_JOINT_LIMITS_DEG,
  DEFAULT_MAX_SPEEDS_DEG_S,
  validateJointTarget,
  isAccidentalZeroTarget,
  moveTimeFor,
} = require('./motion-policy');

const ALLOWED_COMMANDS = new Set([
  'connect',
  'disconnect',
  'status',
  'servo',
  'preset',
  'gripper',
  'software_stop',
  'estop',
  'ping',
]);

function degrees(values) {
  return values.map(value => Number(value) * 180 / Math.PI);
}

class RobotController extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.bridge = new StartouchBridge(config);
    this.latestJointsDeg = null;
    this.latestRobotStateAtMs = null;
    this.stateReady = false;
    this.motionActive = false;
    this.connectPending = false;
    this.started = false;
    this.contracts = createContractValidator();
    this.latestGripperPosition = null;
    this.pendingExecutions = new Map();
    this.seenPrimitiveIds = new Set();
    this._bindBridge();
  }

  _bindBridge() {
    this.bridge.on('message', message => this._handleBridgeMessage(message));
    this.bridge.on('bridge_error', message => {
      this.emit('message', {
        type: 'error',
        code: 'bridge_error',
        msg: message.message,
      });
    });
    this.bridge.on('software_stop_complete', message => {
      this.emit('message', {
        type: 'software_stop',
        complete: true,
        depowered: true,
        msg: 'SDK stopped and motors disabled',
        ts: message.ts || Date.now(),
      });
    });
    this.bridge.on('software_stop_timeout', message => {
      this.emit('message', {
        type: 'software_stop',
        complete: false,
        depowered: false,
        msg: message.message,
        ts: Date.now(),
      });
    });
  }

  async start(timeoutMs = 3000) {
    if (this.started) return;
    this.started = true;
    await new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timeout);
        this.bridge.off('bridge_ready', onReady);
        this.bridge.off('bridge_error', onError);
      };
      const onReady = () => {
        cleanup();
        resolve();
      };
      const onError = message => {
        cleanup();
        reject(new Error(message.message));
      };
      const timeout = setTimeout(() => {
        cleanup();
        reject(new Error('Startouch bridge readiness timeout'));
      }, timeoutMs);

      this.bridge.once('bridge_ready', onReady);
      this.bridge.once('bridge_error', onError);
      this.bridge.start();
    });
  }

  configMessage() {
    return {
      type: 'config',
      presets: { home: [0, 0, 0, 0, 0, 0] },
      jointLimits: DEFAULT_JOINT_LIMITS_DEG,
      model: {
        name: 'Startouch FastTouchV3',
        source: 'models/startouch-v3/FastTouchV3.SLDASM.urdf',
      },
      connection: this.bridge.getInfo(),
      motion: {
        jointMaxSpeedsDegS: DEFAULT_MAX_SPEEDS_DEG_S,
        speedScale: this.config.speedScale,
        commandedSpeedsDegS: DEFAULT_MAX_SPEEDS_DEG_S.map(
          speed => speed * this.config.speedScale,
        ),
        minMoveTimeSec: this.config.minMoveTimeSec,
        maxMoveTimeSec: this.config.maxMoveTimeSec,
      },
      camera: { ready: false, mode: 'vision-service' },
      visionSafety: {
        robotExecutionEnabled: false,
        activeViewExecutionRequested: false,
        activeViewExecutionEnabled: false,
      },
    };
  }

  health() {
    return {
      status: this.bridge.ready ? 'ready' : 'degraded',
      serviceId: 'robot',
      mode: this.config.simulate ? 'simulation' : (this.config.dryRun ? 'dry-run' : 'hardware'),
      robot: {
        connected: this.bridge.connected,
        stateReady: this.stateReady,
        moving: this.motionActive,
        lastStateAt: this.latestRobotStateAtMs,
      },
    };
  }

  handleCommand(message, reply) {
    if (!message || typeof message !== 'object' || !ALLOWED_COMMANDS.has(message.cmd)) {
      reply({ type: 'error', code: 'unsupported_command', msg: 'Unsupported robot command' });
      return;
    }

    switch (message.cmd) {
      case 'ping':
        reply({ type: 'pong', ts: Date.now() });
        return;
      case 'connect':
        if (this.bridge.connected) {
          this.bridge.send({ cmd: 'get_state' });
          return;
        }
        if (this.connectPending) {
          reply({ type: 'error', code: 'connect_pending', msg: 'Startouch SDK is connecting' });
          return;
        }
        this.connectPending = this.bridge.send({ cmd: 'connect' });
        return;
      case 'disconnect':
        this.bridge.send({ cmd: 'disconnect', reason: 'browser_request' });
        return;
      case 'status':
        this.bridge.send({ cmd: 'get_state' });
        return;
      case 'software_stop':
      case 'estop':
        if (!this.bridge.softwareStop()) {
          reply({ type: 'error', code: 'robot_not_connected', msg: 'Startouch SDK is not connected' });
        }
        return;
      case 'preset':
        if (message.name !== 'home') {
          reply({ type: 'error', code: 'unknown_preset', msg: 'Unknown preset' });
          return;
        }
        this._sendJointMotion([0, 0, 0, 0, 0, 0], 'preset:home', reply);
        return;
      case 'servo':
        this._sendJointMotion(message.joints, 'servo', reply);
        return;
      case 'gripper':
        this._sendGripper(message.position, reply);
        return;
      default:
        reply({ type: 'error', code: 'unsupported_command', msg: 'Unsupported robot command' });
    }
  }

  executePrimitive(primitive, reply) {
    const validation = this.contracts.validate('thirdhand.execution-primitive.v1', primitive);
    if (!validation.ok) {
      reply({ type: 'execution.status', status: 'failed', code: 'primitive_invalid', errors: validation.errors });
      return;
    }
    if (this.seenPrimitiveIds.has(primitive.primitiveId)) {
      reply({ type: 'execution.status', status: 'failed', code: 'primitive_replayed', primitiveId: primitive.primitiveId });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError) {
      reply({
        type: 'execution.status', status: 'failed', code: readinessError.code,
        message: readinessError.msg, primitiveId: primitive.primitiveId,
      });
      return;
    }
    if (this.pendingExecutions.size > 0) {
      reply({ type: 'execution.status', status: 'failed', code: 'motion_active', primitiveId: primitive.primitiveId });
      return;
    }

    this.seenPrimitiveIds.add(primitive.primitiveId);
    if (this.seenPrimitiveIds.size > 1024) {
      this.seenPrimitiveIds.delete(this.seenPrimitiveIds.values().next().value);
    }
    const requestId = `execution:${primitive.primitiveId}`;
    const pending = {
      primitive,
      reply,
      requestId,
      acceptedAt: Date.now(),
      beforeJoints: [...this.latestJointsDeg],
      timer: null,
    };
    pending.timer = setTimeout(() => {
      if (!this.pendingExecutions.delete(requestId)) return;
      this.bridge.softwareStop();
      reply({
        type: 'execution.status', status: 'uncertain', code: 'feedback_timeout',
        primitiveId: primitive.primitiveId, taskId: primitive.taskId, traceId: primitive.traceId,
      });
    }, primitive.parameters.timeoutMs);
    this.pendingExecutions.set(requestId, pending);
    const sent = this.bridge.send({
      cmd: 'gripper',
      position: primitive.parameters.positionPercent / 100,
      request_id: requestId,
    });
    if (!sent) {
      clearTimeout(pending.timer);
      this.pendingExecutions.delete(requestId);
      reply({ type: 'execution.status', status: 'failed', code: 'bridge_unavailable', primitiveId: primitive.primitiveId });
      return;
    }
    reply({
      type: 'execution.status', status: 'accepted', primitiveId: primitive.primitiveId,
      taskId: primitive.taskId, traceId: primitive.traceId,
    });
  }

  interruptPrimitive(primitiveId, reason = 'execution_interrupted') {
    for (const [requestId, pending] of this.pendingExecutions) {
      if (pending.primitive.primitiveId !== primitiveId) continue;
      clearTimeout(pending.timer);
      this.pendingExecutions.delete(requestId);
      this.bridge.softwareStop();
      pending.reply({
        type: 'execution.status', status: 'interrupted', code: reason,
        primitiveId, taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
      });
      return true;
    }
    return false;
  }

  _sendJointMotion(joints, source, reply) {
    const validation = validateJointTarget(joints);
    if (!validation.ok) {
      reply({ type: 'error', code: validation.code, msg: validation.message });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError) {
      reply(readinessError);
      return;
    }
    if (isAccidentalZeroTarget(validation.joints, this.latestJointsDeg, source)) {
      reply({
        type: 'error',
        code: 'accidental_zero_target',
        msg: 'Unexpected all-zero target blocked; use the explicit home preset',
      });
      return;
    }

    const timeSec = moveTimeFor(
      validation.joints,
      this.latestJointsDeg,
      DEFAULT_MAX_SPEEDS_DEG_S,
      this.config,
    );
    this.bridge.send({
      cmd: 'move_joint',
      joints_rad: validation.joints.map(value => value * Math.PI / 180),
      time_sec: timeSec,
      request_id: randomUUID(),
      source,
    });
  }

  _sendGripper(position, reply) {
    const normalized = Number(position);
    if (!Number.isFinite(normalized) || normalized < 0 || normalized > 1) {
      reply({
        type: 'error',
        code: 'gripper_limit',
        msg: 'Gripper position must be within [0, 1]',
      });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError) {
      reply(readinessError);
      return;
    }
    this.bridge.send({ cmd: 'gripper', position: normalized, request_id: randomUUID() });
  }

  _motionReadinessError() {
    if (!this.bridge.connected) {
      return { type: 'error', code: 'robot_not_connected', msg: 'Startouch SDK is not connected' };
    }
    if (!this.stateReady || !this.latestJointsDeg || this.latestRobotStateAtMs === null
      || Date.now() - this.latestRobotStateAtMs > 500) {
      return { type: 'error', code: 'robot_state_stale', msg: 'Robot state is not fresh' };
    }
    if (this.motionActive) {
      return { type: 'error', code: 'motion_active', msg: 'Previous motion is still active' };
    }
    return null;
  }

  _handleBridgeMessage(message) {
    if (message.type === 'connection') {
      this.connectPending = false;
      this.stateReady = false;
      this.latestJointsDeg = null;
      this.latestRobotStateAtMs = null;
      this.motionActive = false;
      this.emit('message', {
        ...message,
        mode: 'startouch',
        host: 'localhost',
      });
      return;
    }
    if (message.type === 'robot_state') {
      this.latestJointsDeg = degrees(message.joints_rad || []);
      this.latestRobotStateAtMs = Number(message.ts) || Date.now();
      this.stateReady = this.latestJointsDeg.length === 6
        && this.latestJointsDeg.every(Number.isFinite);
      this.motionActive = message.state === 'MOVING';
      this.latestGripperPosition = Number.isFinite(message.gripper_position)
        ? message.gripper_position
        : null;
      this.emit('message', {
        type: 'robot_state',
        joints: this.latestJointsDeg,
        velocities: degrees(message.velocities_rad_s || []),
        torques: message.torques_nm || [],
        tcpPos: (message.tcp_position_m || []).map(value => Number(value) * 1000),
        tcpEuler: degrees(message.tcp_euler_rad || []),
        gripperPosition: message.gripper_position,
        gripperDistanceMm: Number.isFinite(message.gripper_distance_m)
          ? message.gripper_distance_m * 1000
          : null,
        stateName: message.state,
        ts: message.ts,
      });
      return;
    }
    if (message.type === 'motion_state') {
      this.motionActive = message.state === 'MOVING';
      this.emit('message', { type: 'motion_state', stateName: message.state, ts: message.ts });
      return;
    }
    if (message.type === 'command_accepted') {
      this.emit('message', { ...message, type: 'command_status', status: 'accepted' });
      return;
    }
    if (message.type === 'command_complete') {
      this.motionActive = false;
      const pending = this.pendingExecutions.get(message.request_id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingExecutions.delete(message.request_id);
        const actualPercent = Number(message.actual_position ?? this.latestGripperPosition) * 100;
        const requestedPercent = pending.primitive.parameters.positionPercent;
        const maxJointDeltaDeg = Math.max(...this.latestJointsDeg.map(
          (joint, index) => Math.abs(joint - pending.beforeJoints[index]),
        ));
        const feedbackFresh = this.latestRobotStateAtMs >= pending.acceptedAt;
        const targetReached = message.reached !== false
          && Number.isFinite(actualPercent)
          && Math.abs(actualPercent - requestedPercent) <= pending.primitive.parameters.tolerancePercent;
        const safe = targetReached && feedbackFresh && maxJointDeltaDeg <= 0.5;
        if (maxJointDeltaDeg > 0.5) this.bridge.softwareStop();
        pending.reply({
          type: 'execution.status',
          status: safe ? 'completed' : 'failed',
          code: safe ? 'target_reached' : (maxJointDeltaDeg > 0.5 ? 'unexpected_arm_motion' : 'feedback_invalid'),
          primitiveId: pending.primitive.primitiveId,
          taskId: pending.primitive.taskId,
          traceId: pending.primitive.traceId,
          requestedPercent,
          actualPercent,
          maxJointDeltaDeg,
        });
      }
      this.emit('message', { ...message, type: 'command_status', status: 'complete' });
      return;
    }
    if (message.type === 'error') {
      const pending = this.pendingExecutions.get(message.request_id);
      if (pending) {
        clearTimeout(pending.timer);
        this.pendingExecutions.delete(message.request_id);
        pending.reply({
          type: 'execution.status', status: 'failed', code: 'bridge_error',
          message: message.message, primitiveId: pending.primitive.primitiveId,
          taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
        });
      }
      this.emit('message', { ...message, type: 'error', msg: message.message });
      return;
    }
    if (message.type === 'log') {
      this.emit('message', { type: 'sdk_log', level: message.level, msg: message.message });
    }
  }

  async shutdown() {
    if (!this.started) return;
    this.started = false;
    for (const pending of this.pendingExecutions.values()) clearTimeout(pending.timer);
    this.pendingExecutions.clear();
    this.bridge.shutdown();
    await new Promise(resolve => setTimeout(resolve, 450));
  }
}

module.exports = { ALLOWED_COMMANDS, RobotController };
