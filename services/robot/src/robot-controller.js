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
} = require('./motion-policy');

const ALLOWED_COMMANDS = new Set([
  'connect',
  'disconnect',
  'status',
  'get_state',
  'servo',
  'move_joint',
  'fixed_tcp_demo',
  'move_l',
  'preview_ik',
  'preset',
  'gripper',
  'software_stop',
  'estop',
  'ping',
  'follow_start',
  'follow_target',
  'follow_stop',
]);

const DEFAULT_HOME_PRESET_DEG = Object.freeze([
  -0.163927, -2.611904, -4, 33.058620, 0.338783, 0.185784,
]);
const DEFAULT_ZERO_PRESET_DEG = Object.freeze([
  0, 0, 0, 0, 0, 0,
]);
const DEFAULT_OBSERVE_PRESET_DEG = Object.freeze([
  0, 90, -90, 90, 0, 0,
]);
function degrees(values) {
  return values.map(value => Number(value) * 180 / Math.PI);
}

function finiteVector(value, length) {
  return Array.isArray(value) && value.length === length
    && value.every(Number.isFinite);
}

function linearTargetAllowed(position) {
  if (!finiteVector(position, 3)) return false;
  const limits = [[0.15, 0.66], [-0.65, 0.45], [0.04, 0.65]];
  return position.every(
    (value, index) => value >= limits[index][0] && value <= limits[index][1],
  );
}

function validateAlignmentStep(parameters, latestJointsDeg) {
  if (!finiteVector(latestJointsDeg, 6)) return { ok: false, code: 'robot_state_stale' };
  if (parameters.startJointsDeg.some(
    (value, index) => Math.abs(value - latestJointsDeg[index]) > 0.2,
  )) return { ok: false, code: 'stale_start_joints' };
  const target = validateJointTarget(parameters.targetJointsDeg);
  if (!target.ok) return { ok: false, code: target.code };
  const deltas = target.joints.map((value, index) => value - parameters.startJointsDeg[index]);
  const unchanged = indices => indices.every(index => Math.abs(deltas[index]) <= 1e-6);
  if (parameters.tier === 'wrist') {
    if (!unchanged([0, 1, 2])) return { ok: false, code: 'mixed_joint_tiers' };
    if (deltas.slice(3).some(delta => Math.abs(delta) > 4 + 1e-9)) {
      return { ok: false, code: 'joint_step_exceeded' };
    }
  } else {
    if (parameters.wristExhausted !== true) return { ok: false, code: 'wrist_not_exhausted' };
    if (!unchanged([3, 4, 5])) return { ok: false, code: 'mixed_joint_tiers' };
    if (deltas.slice(0, 3).some(delta => Math.abs(delta) > 2 + 1e-9)) {
      return { ok: false, code: 'joint_step_exceeded' };
    }
  }
  return { ok: true, joints: target.joints };
}

function validatePregrasp(parameters, controller) {
  if (!finiteVector(controller.latestJointsDeg, 6)) {
    return { ok: false, code: 'robot_state_stale' };
  }
  if (controller.stateSequence < parameters.minimumStateSequence) {
    return { ok: false, code: 'stale_state_sequence' };
  }
  if (controller.latestProducerMonotonicNs < parameters.minimumProducerMonotonicNs) {
    return { ok: false, code: 'stale_producer_state' };
  }
  if (parameters.startJointsDeg.some(
    (value, index) => Math.abs(value - controller.latestJointsDeg[index]) > 0.2,
  )) return { ok: false, code: 'stale_start_joints' };
  const target = validateJointTarget(parameters.targetJointsDeg);
  if (!target.ok) return { ok: false, code: target.code };
  if (!linearTargetAllowed(parameters.pregraspTcpPositionM)) {
    return { ok: false, code: 'pregrasp_out_of_workspace' };
  }
  if (parameters.operationMode !== 'pregrasp_only'
      || parameters.speedScale > 0.05
      || parameters.speedScale > controller.config.speedScale) {
    return { ok: false, code: 'pregrasp_safety_profile_invalid' };
  }
  return { ok: true, joints: target.joints };
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
    this.demoActiveRequestId = null;
    this.demoActiveOwner = null;
    this.connectPending = false;
    this.started = false;
    this.contracts = createContractValidator();
    this.latestGripperPosition = null;
    this.pendingExecutions = new Map();
    this.seenPrimitiveIds = new Set();
    this.pendingLowLevel = new Map();
    this.stateSequence = 0;
    this.latestProducerMonotonicNs = Number(process.hrtime.bigint());
    this.pendingStopRequestId = null;
    this.followOwner = null;
    this.followStream = null;
    this.followActive = false;
    this._bindBridge();
  }

  _bindBridge() {
    this.bridge.on('message', message => this._handleBridgeMessage(message));
    this.bridge.on('bridge_error', message => this._handleBridgeMessage({
      ...message, type: 'error', code: message.code || 'bridge_error',
    }));
    this.bridge.on('software_stop_complete', message => {
      this._finalizeInterruptedExecutions('interrupted', null);
      const requestId = this.pendingStopRequestId;
      this.pendingStopRequestId = null;
      if (requestId) {
        this.pendingLowLevel.delete(requestId);
        this.emit('message', {
          type: 'command_status', status: 'complete', command: 'software_stop',
          request_id: requestId, stopped: true,
          applied_state_sequence: this.stateSequence,
          applied_producer_monotonic_ns: this.latestProducerMonotonicNs,
          robot_healthy: false,
        });
      }
      this.emit('message', {
        type: 'software_stop',
        complete: true,
        depowered: true,
        msg: 'SDK stopped and motors disabled',
        ts: message.ts || Date.now(),
      });
    });
    this.bridge.on('software_stop_timeout', message => {
      this._finalizeInterruptedExecutions('uncertain', 'stop_feedback_timeout');
      this.pendingStopRequestId = null;
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
      presets: {
        zero: [...(this.config.zeroPresetDeg || DEFAULT_ZERO_PRESET_DEG)],
        home: [...(this.config.homePresetDeg || DEFAULT_HOME_PRESET_DEG)],
        observe: [...DEFAULT_OBSERVE_PRESET_DEG],
      },
      jointLimits: DEFAULT_JOINT_LIMITS_DEG,
      model: {
        name: 'Startouch FastTouchV3',
        source: 'models/startouch-v3/FastTouchV3.SLDASM.urdf',
      },
      connection: this.bridge.getInfo(),
      motion: {
        jointMaxSpeedsDegS: DEFAULT_MAX_SPEEDS_DEG_S,
        planningMode: 'sdk_joint_speed',
        speedScale: Math.min(0.10, this.config.speedScale ?? 0.05),
        commandedSpeedsDegS: DEFAULT_MAX_SPEEDS_DEG_S.map(
          speed => speed * Math.min(0.10, this.config.speedScale ?? 0.05),
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

  capabilityResponse(nonce) {
    return {
      type: 'capability_response',
      schema: 'thirdhand-robot-capability-v1',
      nonce,
      protocol_version: 'thirdhand-robot-lowlevel-v1',
      pose_frame: 'robot_flange',
      commands: ['move_l', 'preview_ik', 'move_joint', 'fixed_tcp_demo', 'gripper', 'preset', 'software_stop', 'get_state',
        'follow_start', 'follow_target', 'follow_stop'],
      correlated_completions: true,
      software_stop_ack: true,
      software_stop_state_boundary: true,
      state_units: {
        position: 'm', orientation: 'rad', joints: 'deg',
        joint_velocity: 'deg/s', gripper: 'm',
      },
      state_stream: {
        sequence: 'uint53', producer_monotonic_ns: 'uint53',
        strictly_increasing: true,
      },
      state_sequence: this.stateSequence,
      producer_monotonic_ns: this.latestProducerMonotonicNs,
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
        fixedTcpDemoActive: Boolean(this.demoActiveRequestId),
        lastStateAt: this.latestRobotStateAtMs,
        continuousFollow: {
          j1MaxSpeedDegS: this.config.followJ1MaxSpeedDegS ?? 50,
          j4MaxSpeedDegS: 1000 * Math.min(0.05, this.config.speedScale ?? 0.05),
        },
      },
    };
  }

  handleCommand(message, reply, owner = 'local') {
    const originalReply = reply;
    reply = response => originalReply({
      ...response,
      ...(typeof message?.request_id === 'string' && message.request_id
        ? { request_id: message.request_id } : {}),
    });
    if (!message || typeof message !== 'object' || !ALLOWED_COMMANDS.has(message.cmd)) {
      reply({ type: 'error', code: 'unsupported_command', msg: 'Unsupported robot command' });
      return;
    }

    switch (message.cmd) {
      case 'follow_start':
      case 'follow_target':
      case 'follow_stop':
        this._sendFollow(message, reply, owner);
        return;
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
      case 'get_state':
        this.bridge.send({ cmd: 'get_state' });
        return;
      case 'software_stop':
      case 'estop': {
        const requestId = typeof message.request_id === 'string' && message.request_id
          ? message.request_id : randomUUID();
        this.pendingStopRequestId = requestId;
        this.pendingLowLevel.set(requestId, 'software_stop');
        if (!this.bridge.softwareStop(requestId)) {
          this.pendingStopRequestId = null;
          this.pendingLowLevel.delete(requestId);
          reply({ type: 'error', code: 'robot_not_connected', msg: 'Startouch SDK is not connected' });
        }
        return;
      }
      case 'preset': {
        const presets = {
          zero: this.config.zeroPresetDeg || DEFAULT_ZERO_PRESET_DEG,
          home: this.config.homePresetDeg || DEFAULT_HOME_PRESET_DEG,
          observe: DEFAULT_OBSERVE_PRESET_DEG,
        };
        const target = presets[message.name];
        if (!target) {
          reply({ type: 'error', code: 'unknown_preset', msg: 'Unknown preset' });
          return;
        }
        this._sendJointMotion(
          target, `preset:${message.name}`, reply,
          message.request_id, 'preset',
        );
        return;
      }
      case 'servo':
        this._sendJointMotion(
          message.joints, 'servo', reply, message.request_id, 'move_joint',
        );
        return;
      case 'move_joint':
        this._sendJointMotion(
          message.joints_deg, message.source || 'move_joint', reply,
          message.request_id, 'move_joint', message.time_sec,
        );
        return;
      case 'fixed_tcp_demo':
        this._startFixedTcpDemo(message, reply, owner);
        return;
      case 'move_l':
        this._sendLinearMotion(message, reply);
        return;
      case 'preview_ik':
        this._sendIkPreview(message, reply);
        return;
      case 'gripper':
        this._sendGripper(message.position, reply, message.request_id, message.grasp_feedback_upper);
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
    if (primitive.operation === 'vision.align.step') {
      const alignment = validateAlignmentStep(primitive.parameters, this.latestJointsDeg);
      if (!alignment.ok) {
        reply({
          type: 'execution.status', status: 'failed', code: alignment.code,
          primitiveId: primitive.primitiveId, taskId: primitive.taskId, traceId: primitive.traceId,
        });
        return;
      }
      this._executeAlignmentPrimitive(primitive, alignment, reply);
      return;
    }
    if (primitive.operation === 'grasp.pregrasp') {
      const pregrasp = validatePregrasp(primitive.parameters, this);
      if (!pregrasp.ok) {
        reply({
          type: 'execution.status', status: 'failed', code: pregrasp.code,
          primitiveId: primitive.primitiveId, taskId: primitive.taskId, traceId: primitive.traceId,
        });
        return;
      }
      this._executePregraspPrimitive(primitive, pregrasp, reply);
      return;
    }
    this._executeGripperPrimitive(primitive, reply);
  }

  _beginExecution(primitive, reply, kind) {
    const requestId = `execution:${primitive.primitiveId}`;
    const pending = {
      primitive, reply, requestId, kind,
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
    return pending;
  }

  _acceptExecution(pending) {
    const { primitive, reply } = pending;
    reply({
      type: 'execution.status', status: 'accepted', primitiveId: primitive.primitiveId,
      taskId: primitive.taskId, traceId: primitive.traceId,
    });
  }

  _failExecutionSend(pending) {
    clearTimeout(pending.timer);
    this.pendingExecutions.delete(pending.requestId);
    pending.reply({
      type: 'execution.status', status: 'failed', code: 'bridge_unavailable',
      primitiveId: pending.primitive.primitiveId,
    });
  }

  _executeGripperPrimitive(primitive, reply) {
    const pending = this._beginExecution(primitive, reply, 'gripper');
    const sent = this.bridge.send({
      cmd: 'gripper',
      position: primitive.parameters.positionPercent / 100,
      request_id: pending.requestId,
    });
    if (!sent) {
      this._failExecutionSend(pending);
      return;
    }
    this._acceptExecution(pending);
  }

  _executeAlignmentPrimitive(primitive, alignment, reply) {
    const pending = this._beginExecution(primitive, reply, 'alignment');
    this.pendingLowLevel.set(pending.requestId, 'move_joint');
    const sent = this.bridge.send({
      cmd: 'move_joint',
      joints_rad: alignment.joints.map(value => value * Math.PI / 180),
      speed_percent: Math.min(0.10, this.config.speedScale ?? 0.05),
      request_id: pending.requestId,
      source: `vision-align:${primitive.parameters.tier}`,
    });
    if (!sent) {
      this.pendingLowLevel.delete(pending.requestId);
      this._failExecutionSend(pending);
      return;
    }
    this._acceptExecution(pending);
  }

  _executePregraspPrimitive(primitive, pregrasp, reply) {
    const pending = this._beginExecution(primitive, reply, 'pregrasp');
    this.pendingLowLevel.set(pending.requestId, 'move_joint');
    const sent = this.bridge.send({
      cmd: 'move_joint',
      joints_rad: pregrasp.joints.map(value => value * Math.PI / 180),
      speed_percent: Math.min(0.05, this.config.speedScale ?? 0.05, primitive.parameters.speedScale),
      request_id: pending.requestId,
      source: 'protected-grasp-pregrasp',
    });
    if (!sent) {
      this.pendingLowLevel.delete(pending.requestId);
      this._failExecutionSend(pending);
      return;
    }
    this._acceptExecution(pending);
  }

  interruptPrimitive(primitiveId, reason = 'execution_interrupted') {
    for (const [requestId, pending] of this.pendingExecutions) {
      if (pending.primitive.primitiveId !== primitiveId) continue;
      if (pending.stopRequested) return true;
      pending.stopRequested = true;
      pending.stopReason = reason;
      if (!this.bridge.softwareStop()) {
        clearTimeout(pending.timer);
        this.pendingExecutions.delete(requestId);
        pending.reply({
          type: 'execution.status', status: 'uncertain', code: 'stop_request_failed',
          primitiveId, taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
        });
      }
      return true;
    }
    return false;
  }

  _finalizeInterruptedExecutions(status, fallbackCode) {
    for (const [requestId, pending] of [...this.pendingExecutions]) {
      if (!pending.stopRequested) continue;
      clearTimeout(pending.timer);
      this.pendingExecutions.delete(requestId);
      pending.reply({
        type: 'execution.status', status,
        code: fallbackCode || pending.stopReason || 'execution_interrupted',
        primitiveId: pending.primitive.primitiveId,
        taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
        sessionId: pending.primitive.parameters?.sessionId,
      });
    }
  }

  interruptSession(sessionId, reason = 'execution_interrupted') {
    let interrupted = false;
    for (const pending of [...this.pendingExecutions.values()]) {
      if (pending.primitive.parameters?.sessionId !== sessionId) continue;
      interrupted = this.interruptPrimitive(pending.primitive.primitiveId, reason) || interrupted;
    }
    return interrupted;
  }

  _startFixedTcpDemo(message, reply, owner) {
    const requestId = message.request_id;
    const xyz = message.fixed_xyz ?? [0.48, 0, 0.36];
    const useCurrentTcp = message.use_current_tcp_xyz ?? false;
    const cone = message.max_cone_deg ?? 50;
    const duration = message.duration_sec ?? 60;
    if (typeof requestId !== 'string' || !/^[\w:-]{1,120}$/.test(requestId)
        || typeof message.execute !== 'boolean'
        || typeof useCurrentTcp !== 'boolean'
        || !linearTargetAllowed(xyz)
        || !Number.isFinite(cone) || cone < 25 || cone > 50
        || !Number.isFinite(duration) || duration < 10 || duration > 60) {
      reply({ type: 'error', code: 'fixed_tcp_demo_invalid', request_id: requestId });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError || this.pendingExecutions.size > 0) {
      reply({ ...(readinessError || { type: 'error', code: 'execution_active' }), request_id: requestId });
      return;
    }
    this.demoActiveRequestId = requestId;
    this.demoActiveOwner = owner;
    this.pendingLowLevel.set(requestId, 'fixed_tcp_demo');
    if (!this.bridge.send({ cmd: 'fixed_tcp_demo', request_id: requestId,
      execute: message.execute, fixed_xyz: xyz, use_current_tcp_xyz: useCurrentTcp,
      max_cone_deg: cone, duration_sec: duration })) {
      this.demoActiveRequestId = null;
      this.demoActiveOwner = null;
      this.pendingLowLevel.delete(requestId);
      reply({ type: 'error', code: 'bridge_unavailable', request_id: requestId });
    }
  }

  interruptFixedTcpDemo(requestId, owner) {
    return this.demoActiveRequestId === requestId && this.demoActiveOwner === owner
      && this.bridge.softwareStop();
  }

  _sendJointMotion(
    joints, source, reply, suppliedRequestId = null,
    command = 'move_joint', suppliedTimeSec = null,
  ) {
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

    const requestId = typeof suppliedRequestId === 'string' && suppliedRequestId
      ? suppliedRequestId : randomUUID();
    this.pendingLowLevel.set(requestId, command);
    const sent = this.bridge.send({
      cmd: 'move_joint',
      joints_rad: validation.joints.map(value => value * Math.PI / 180),
      speed_percent: Math.min(0.10, this.config.speedScale ?? 0.05),
      request_id: requestId,
      source,
    });
    if (!sent) {
      this.pendingLowLevel.delete(requestId);
      reply({
        type: 'error', code: 'bridge_unavailable',
        msg: 'Robot bridge is unavailable',
      });
    }
  }

  _sendIkPreview(message, reply) {
    const requestId = typeof message.request_id === 'string' && message.request_id
      ? message.request_id : randomUUID();
    if (!linearTargetAllowed(message.position) || !finiteVector(message.euler, 3)) {
      reply({ type: 'error', code: 'linear_target_invalid', msg: 'Cartesian target is outside the approved workspace', request_id: requestId });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError) {
      reply({ ...readinessError, request_id: requestId });
      return;
    }
    if (!this.bridge.send({
      cmd: 'preview_ik', position: [...message.position], euler: [...message.euler],
      request_id: requestId,
    })) {
      reply({ type: 'error', code: 'bridge_unavailable', msg: 'Robot bridge is unavailable', request_id: requestId });
    }
  }

  _sendLinearMotion(message, reply) {
    const precision = {};
    for (const [field, upper] of [['position_tolerance_m', 0.04], ['orientation_tolerance_rad', 0.4]]) {
      if (message[field] === undefined) continue;
      const value = message[field];
      if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0 || value > upper) {
        reply({type:'error',code:'linear_precision_invalid',msg:'Invalid '+field,request_id:message.request_id});
        return;
      }
      precision[field] = value;
    }
    if (!linearTargetAllowed(message.position) || !finiteVector(message.euler, 3)) {
      reply({
        type: 'error', code: 'linear_target_invalid',
        msg: 'Cartesian target is outside the approved workspace',
      });
      return;
    }
    const readinessError = this._motionReadinessError();
    if (readinessError) {
      reply(readinessError);
      return;
    }
    const requestId = typeof message.request_id === 'string' && message.request_id
      ? message.request_id : randomUUID();
    this.pendingLowLevel.set(requestId, 'move_l');
    const sent = this.bridge.send({
      cmd: 'move_l',
      position: [...message.position],
      euler: [...message.euler],
      speed_percent: Math.min(0.10, this.config.speedScale ?? 0.05),
      request_id: requestId,
      source: message.source || 'robot-service',
      ...precision,
    });
    if (!sent) {
      this.pendingLowLevel.delete(requestId);
      reply({
        type: 'error', code: 'bridge_unavailable',
        msg: 'Robot bridge is unavailable',
      });
    }
  }

  _sendGripper(position, reply, suppliedRequestId = null, graspFeedbackUpper = undefined) {
    const normalized = Number(position);
    if (graspFeedbackUpper !== undefined && (normalized !== 0.35 || graspFeedbackUpper !== 0.4)) {
      reply({type:'error',code:'gripper_contact_invalid',msg:'Contact policy requires target 35% and upper 40%'});
      return;
    }
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
    const requestId = typeof suppliedRequestId === 'string' && suppliedRequestId
      ? suppliedRequestId : randomUUID();
    this.pendingLowLevel.set(requestId, 'gripper');
    const sent = this.bridge.send({
      cmd: 'gripper', position: normalized, request_id: requestId,
      ...(graspFeedbackUpper === undefined ? {} : {grasp_feedback_upper:graspFeedbackUpper}),
    });
    if (!sent) {
      this.pendingLowLevel.delete(requestId);
      reply({
        type: 'error', code: 'bridge_unavailable',
        msg: 'Robot bridge is unavailable',
      });
    }
  }

  _sendFollow(message, reply, owner) {
    if (typeof message.stream_id !== 'string' || !message.stream_id || message.stream_id.length > 128) {
      reply({ type: 'error', code: 'follow_stream_invalid', msg: 'Follow stream ID required' });
      return;
    }
    if (message.cmd === 'follow_start') {
      const error = this._motionReadinessError();
      if (error) { reply(error); return; }
      this.followOwner = owner;
      this.followStream = message.stream_id;
    } else if (this.followOwner !== owner || this.followStream !== message.stream_id) {
      reply({ type: 'error', code: 'follow_stream_mismatch', msg: 'Not the active follow connection' });
      return;
    }
    let joints;
    if (message.cmd === 'follow_target') {
      const validation = validateJointTarget(message.joints_deg);
      if (!validation.ok || !Number.isSafeInteger(message.sequence) || message.sequence < 0
          || !Number.isFinite(message.observed_at_ms)
          || Date.now() - message.observed_at_ms > 500
          || Date.now() - message.observed_at_ms < -50
          || !this.stateReady || Date.now() - this.latestRobotStateAtMs > 500) {
        reply({ type: 'error', code: 'follow_target_invalid', msg: 'Fresh bounded follow target required' });
        return;
      }
      joints = validation.joints.map(value => value * Math.PI / 180);
    }
    const requestId = message.request_id || randomUUID();
    this.pendingLowLevel.set(requestId, message.cmd);
    if (!this.bridge.send({
      cmd: message.cmd, request_id: requestId, stream_id: message.stream_id,
      joints_rad: joints, sequence: message.sequence, observed_at_ms: message.observed_at_ms,
    })) {
      this.pendingLowLevel.delete(requestId);
      if (message.cmd === 'follow_start') this.followOwner = this.followStream = null;
      reply({ type: 'error', code: 'bridge_unavailable', msg: 'Robot bridge unavailable' });
    }
  }

  releaseFollow(owner) {
    if (this.followOwner !== owner || this.followStream === null) return;
    this.bridge.send({ cmd: 'follow_stop', stream_id: this.followStream });
  }

  _motionReadinessError() {
    if (!this.bridge.connected) {
      return { type: 'error', code: 'robot_not_connected', msg: 'Startouch SDK is not connected' };
    }
    if (!this.stateReady || !this.latestJointsDeg || this.latestRobotStateAtMs === null
      || Date.now() - this.latestRobotStateAtMs > 500) {
      return { type: 'error', code: 'robot_state_stale', msg: 'Robot state is not fresh' };
    }
    if (this.motionActive || this.followOwner !== null) {
      return { type: 'error', code: 'motion_active', msg: 'Previous motion is still active' };
    }
    if (this.demoActiveRequestId) {
      return { type: 'error', code: 'fixed_tcp_demo_active', msg: 'Fixed TCP demo is active' };
    }
    return null;
  }

  _completeAlignmentIfReady(pending) {
    if (pending.stopRequested || !pending.commandComplete || this.motionActive || !this.stateReady
        || this.latestRobotStateAtMs < pending.acceptedAt) return false;
    const target = pending.primitive.parameters.targetJointsDeg;
    const maxTargetErrorDeg = Math.max(...this.latestJointsDeg.map(
      (joint, index) => Math.abs(joint - target[index]),
    ));
    const safe = pending.commandReached && maxTargetErrorDeg <= 0.5;
    clearTimeout(pending.timer);
    this.pendingExecutions.delete(pending.requestId);
    pending.reply({
      type: 'execution.status', status: safe ? 'completed' : 'failed',
      code: safe ? 'target_reached' : 'feedback_invalid',
      primitiveId: pending.primitive.primitiveId,
      taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
      sessionId: pending.primitive.parameters.sessionId,
      motionEpoch: pending.primitive.parameters.motionEpoch,
      actualJointsDeg: [...this.latestJointsDeg], maxTargetErrorDeg,
    });
    return true;
  }

  _handleBridgeMessage(message) {
    if (message.type === 'follow_state') {
      this.followActive = message.active === true;
      this.motionActive = this.followActive;
      if (!this.followActive) this.followOwner = this.followStream = null;
      this.emit('message', {
        ...message,
        hold_joints_deg: message.hold_joints_rad ? degrees(message.hold_joints_rad) : undefined,
      });
      return;
    }
    if (message.type === 'connection') {
      this.demoActiveRequestId = null;
      this.demoActiveOwner = null;
      this.connectPending = false;
      this.stateReady = false;
      this.latestJointsDeg = null;
      this.latestRobotStateAtMs = null;
      this.motionActive = false;
      this.followOwner = this.followStream = null;
      this.followActive = false;
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
      this.stateSequence += 1;
      this.latestProducerMonotonicNs = Math.max(
        this.latestProducerMonotonicNs + 1,
        Number(process.hrtime.bigint()),
      );
      const velocitiesDegS = degrees(message.velocities_rad_s || []);
      const flangePositionM = [...(message.tcp_position_m || [])];
      const flangeEulerRad = [...(message.tcp_euler_rad || [])];
      this.emit('message', {
        type: 'robot_state',
        connected: this.bridge.connected,
        healthy: this.stateReady,
        moving: this.motionActive,
        state_sequence: this.stateSequence,
        producer_monotonic_ns: this.latestProducerMonotonicNs,
        pose_frame: 'robot_flange',
        flange_position_m: flangePositionM,
        flange_euler_rad: flangeEulerRad,
        joints_deg: [...this.latestJointsDeg],
        velocities_deg_s: velocitiesDegS,
        gripper_width_m: message.gripper_distance_m,
        gripper_position: message.gripper_position,
        joints: this.latestJointsDeg,
        velocities: velocitiesDegS,
        torques: message.torques_nm || [],
        tcpPos: flangePositionM.map(value => Number(value) * 1000),
        tcpEuler: degrees(message.tcp_euler_rad || []),
        gripperPosition: message.gripper_position,
        gripperDistanceMm: Number.isFinite(message.gripper_distance_m)
          ? message.gripper_distance_m * 1000
          : null,
        stateName: message.state,
        ts: message.ts,
      });
      for (const pending of this.pendingExecutions.values()) {
        if (pending.kind === 'alignment' || pending.kind === 'pregrasp') {
          this._completeAlignmentIfReady(pending);
        }
      }
      return;
    }
    if (message.type === 'motion_state') {
      this.motionActive = message.state === 'MOVING';
      this.emit('message', { type: 'motion_state', stateName: message.state, ts: message.ts });
      return;
    }
    if (message.type === 'ik_preview') {
      this.emit('message', {
        type: 'ik_preview', request_id: message.request_id, ok: message.ok === true,
        joints_deg: message.ok === true ? degrees(message.joints_rad || []) : [],
      });
      return;
    }
    if (message.type === 'command_accepted') {
      const command = this.pendingLowLevel.get(message.request_id) || message.command;
      if (command === 'follow_start' || command === 'follow_target') {
        this.pendingLowLevel.delete(message.request_id);
      }
      this.emit('message', {
        ...message, command, type: 'command_status', status: 'accepted',
      });
      return;
    }
    if (message.type === 'command_complete') {
      if (message.request_id === this.demoActiveRequestId) {
        this.demoActiveRequestId = this.demoActiveOwner = null;
      }
      this.motionActive = false;
      const pending = this.pendingExecutions.get(message.request_id);
      if (pending) {
        if (pending.kind === 'alignment' || pending.kind === 'pregrasp') {
          pending.commandComplete = true;
          pending.commandReached = message.reached !== false;
          this._completeAlignmentIfReady(pending);
        } else {
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
            type: 'execution.status', status: safe ? 'completed' : 'failed',
            code: safe ? 'target_reached' : (maxJointDeltaDeg > 0.5 ? 'unexpected_arm_motion' : 'feedback_invalid'),
            primitiveId: pending.primitive.primitiveId,
            taskId: pending.primitive.taskId, traceId: pending.primitive.traceId,
            requestedPercent, actualPercent, maxJointDeltaDeg,
          });
        }
      }
      const command = this.pendingLowLevel.get(message.request_id) || message.command;
      this.pendingLowLevel.delete(message.request_id);
      this.emit('message', {
        ...message, command, type: 'command_status', status: 'complete',
        reached: message.reached !== false,
        actual_joints_deg: message.actual_joints_rad
          ? degrees(message.actual_joints_rad) : [...(this.latestJointsDeg || [])],
        actual_width_m: Number.isFinite(message.actual_position)
          ? message.actual_position * 0.080 : undefined,
        robot_healthy: this.stateReady,
      });
      return;
    }
    if (message.type === 'error') {
      if (message.request_id === this.demoActiveRequestId) {
        this.demoActiveRequestId = this.demoActiveOwner = null;
      }
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
      const command = this.pendingLowLevel.get(message.request_id)
        || message.command || null;
      if (command === 'follow_start') {
        this.followOwner = this.followStream = null;
        this.followActive = false;
      }
      this.pendingLowLevel.delete(message.request_id);
      this.emit('message', {
        ...message, type: 'error', command,
        reason: message.message, msg: message.message,
      });
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
    this.pendingLowLevel.clear();
    this.pendingStopRequestId = null;
    this.bridge.shutdown();
    await new Promise(resolve => setTimeout(resolve, 450));
  }
}

module.exports = {
  ALLOWED_COMMANDS, RobotController, validateAlignmentStep, validatePregrasp,
};
