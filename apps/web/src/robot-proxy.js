'use strict';

const { randomUUID } = require('crypto');
const { WebSocket } = require('ws');
const fs = require('fs');
const { cameraXTarget, normalizeCameraXStep } = require('./language/camera-x-step');
const { BottlePickAdapter } = require('./language/bottle-pick-adapter');
const { LanguageUpstreamBridge } = require('./language/language-upstream-bridge');
const { ManualJointOrchestrator } = require('./language/manual-joint-control');
const {
  DIRECTIONAL_SKILL,
  DirectionalJointOrchestrator,
} = require('./language/directional-joint-control');
const {
  PICK_SKILL,
  SkillExecutorRegistry,
} = require('./language/skill-executor-registry');

const ROBOT_COMMANDS = new Set([
  'connect',
  'disconnect',
  'status',
  'servo',
  'move_l',
  'preview_ik',
  'preset',
  'fixed_tcp_demo',
  'gripper',
  'software_stop',
  'estop',
  'ping',
  'get_state',
  'teach_start',
  'teach_hold',
  'teach_keepalive',
]);

function sendJson(socket, message) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

function parseJson(data) {
  try {
    return JSON.parse(data.toString('utf8'));
  } catch {
    return null;
  }
}

function isCapabilityRequest(message){
  return message?.type==='capability_request'&&message.schema==='thirdhand-robot-capability-v1'
    &&Object.keys(message).length===3&&typeof message.nonce==='string'&&message.nonce.length>0&&message.nonce.length<=128;
}

class RobotProxy {
  constructor(robotWsUrl, languageConfig = {}) {
    this.robotWsUrl = robotWsUrl;
    this.languageConfig = languageConfig;
    this.cameraMount = null;
    this.cameraDirectionValidated = false;
    try {
      this.cameraMount = JSON.parse(fs.readFileSync(languageConfig.cameraMountFile, 'utf8'));
      const proof = JSON.parse(fs.readFileSync(languageConfig.cameraDirectionValidationFile, 'utf8'));
      const mountId = this.cameraMount?.camera?.camera_mount_id;
      const serial = this.cameraMount?.camera?.camera_serial;
      this.cameraDirectionValidated = typeof mountId === 'string' && mountId.trim() !== '' &&
        typeof serial === 'string' && serial.trim() !== '' &&
        proof.cameraMountId === mountId && proof.cameraSerial === serial &&
        proof.leftMovesLeft === true && proof.rightMovesRight === true;
    } catch {
      // A missing mount or direction proof leaves real camera-frame motion disabled.
    }
    this.sessions = new Set();
    this.forwardedMotion = new Map();
    this.controlUncertainAtMs = null;
    this.languageCandidateOwners = new Map();
    this.skillExecutors = new SkillExecutorRegistry();
    this.skillExecutors.register(PICK_SKILL, new BottlePickAdapter({
      visionBaseUrl: languageConfig.visionHttpUrl,
      vaBaseUrl: languageConfig.vaHttpUrl,
    }));
    this.languageUpstream = new LanguageUpstreamBridge({
      endpoint: robotWsUrl,
      stateMaxAgeMs: languageConfig.stateMaxAgeMs,
      maxDeltaDeg: languageConfig.maxDeltaDeg,
      maxSpeedScale: languageConfig.speedScale,
      probeOnOpen: false,
    });

    const moveTimeFor = joints => {
      const current = this.languageUpstream.getRobotState().jointsDeg;
      const reference = Array.isArray(current) ? current : joints.map(() => 0);
      const speeds = languageConfig.jointMaxSpeedsDegS;
      const hardMinimum = Math.max(
        ...joints.map((value, index) => Math.abs(value - reference[index]) / speeds[index]),
      );
      const requested = Math.max(
        ...joints.map((value, index) => (
          Math.abs(value - reference[index]) / (speeds[index] * languageConfig.speedScale)
        )),
      );
      const bounded = Math.max(
        languageConfig.minMoveTimeSec,
        Math.min(languageConfig.maxMoveTimeSec, requested),
      );
      return Math.max(hardMinimum, bounded);
    };

    const common = {
      jointLimitsDeg: languageConfig.jointLimitsDeg,
      speedScale: languageConfig.speedScale,
      stateMaxAgeMs: languageConfig.stateMaxAgeMs,
      jointToleranceDeg: languageConfig.jointToleranceDeg,
      moveTimeFor,
      sendRobot: command => this._sendLanguageRobot(command),
      softwareStop: () => this.languageUpstream.softwareStop(),
      getRobotState: () => this.languageUpstream.getRobotState(),
      onMessage: (browser, message) => sendJson(browser, message),
    };

    this.languageController = new ManualJointOrchestrator({
      ...common,
      enabled: languageConfig.realControlEnabled,
      maxDeltaDeg: languageConfig.maxDeltaDeg,
      getHomeTarget: () => this.languageUpstream.getPreset('home'),
      gripperOpenTarget: languageConfig.gripperOpenTarget,
      gripperCloseTarget: languageConfig.gripperCloseTarget,
      gripperTimeoutMs: languageConfig.gripperTimeoutMs,
      skillExecutors: this.skillExecutors,
      planCameraX: params => cameraXTarget(
        this.languageUpstream.getRobotState(), params, this.cameraMount),
      previewPose: (position, euler) => this.languageUpstream.previewIk(position, euler),
      cameraProbeEnabled: languageConfig.cameraProbeEnabled,
      cameraRealControlEnabled: languageConfig.cameraRealControlEnabled &&
        this.cameraDirectionValidated,
    });
    this.directionalController = new DirectionalJointOrchestrator({
      ...common,
      enabled: languageConfig.directionalEnabled,
      realControlEnabled: languageConfig.directionalRealControlEnabled,
    });

    this.languageUpstream.on('message', message => {
      this._reconcileControl(message);
      this.languageController.handleBridgeEvent(message);
      this.directionalController.handleBridgeEvent(message);
    });
    this.languageUpstream.on('status', status => {
      this.broadcast({ type: 'language_backend', ...status });
    });
    this.languageUpstream.on('log', message => {
      console.warn(`[Language upstream] ${message.message}`);
    });
    this.languageUpstream.start();
  }

  languageRuntimeConfig() {
    return {
      ...this.languageController.runtimeConfig(),
      directional: this.directionalController.runtimeConfig(),
      executionBackend: 'formal-3000-upstream',
      manualControlBackend: 'formal-3000-upstream',
      cameraX: {
        previewAvailable: Boolean(this.cameraMount),
        probeEnabled: this.languageConfig.cameraProbeEnabled,
        realControlEnabled: this.languageConfig.cameraRealControlEnabled &&
          this.cameraDirectionValidated,
        directionValidated: this.cameraDirectionValidated,
        maxDistanceCm: 10,
        probeMaxDistanceCm: 1,
      },
      upstream: this.languageUpstream.publicStatus(),
    };
  }

  async _previewCameraX(browser, candidate) {
    const params = candidate?.payload?.params;
    const reply = result => sendJson(browser, {
      type: 'skill.candidate.preview',
      candidateId: candidate?.candidateId,
      traceId: candidate?.traceId,
      ...result,
    });
    const checked = normalizeCameraXStep(params);
    if (!checked.ok) return reply({ ok: false, reason: checked.reason });
    const state = this.languageUpstream.getRobotState();
    if (!state.connected || !state.stateFresh || state.stateName !== 'IDLE' ||
        state.motionActive || state.ageMs > 500) {
      return reply({ ok: false, reason: '机器人状态未就绪，不能预览末端平移' });
    }
    const plan = cameraXTarget(state, params, this.cameraMount);
    if (!plan.ok) return reply({ ok: false, reason: plan.reason });
    const ik = await this.languageUpstream.previewIk(plan.position, plan.euler);
    if (!ik.ok) return reply({ ok: false, reason: ik.reason });
    const bound = this.languageController.bindCameraPreview(browser, candidate, {
      originPositionM: state.flangePositionM,
      originEulerRad: state.flangeEulerRad,
      targetPositionM: plan.position,
      targetEulerRad: plan.euler,
      jointsDeg: ik.jointsDeg,
    });
    if (!bound) return reply({ ok: false, reason: '候选已失效，请重新输入末端目标' });
    return reply({
      ok: true, jointsDeg: ik.jointsDeg,
      targetPositionM: plan.position,
      cameraMountId: plan.cameraMountId,
      direction: params.direction,
      distanceCm: params.distanceCm,
      executionMode: this.languageConfig.cameraRealControlEnabled &&
        this.cameraDirectionValidated ? 'real'
        : this.languageConfig.cameraProbeEnabled && params.distanceCm <= 1 ? 'probe'
          : 'blocked',
    });
  }

  broadcast(message) {
    for (const session of this.sessions) sendJson(session.browser, message);
  }

  getRobotState() {
    return this.languageUpstream.getRobotState();
  }

  setGraspInterlock(getStatus) { this.graspInterlock = getStatus; }

  _mayForward(session, message) {
    return !this.graspInterlock?.()?.active || session?.graspOwner === true
      || isCapabilityRequest(message)
      || ['software_stop','estop','status','ping','get_state','preview_ik'].includes(message.cmd);
  }

  _sendLanguageRobot(command) {
    if (!this._mayForward(null,command)) return false;
    return this.languageUpstream.send(command);
  }

  hasActiveControl() {
    return Boolean(this.languageController.active || this.directionalController.active
      || this.controlUncertainAtMs !== null || this.forwardedMotion.size
      || [...this.sessions].some(s => s.queue.some(raw =>
        ['servo','move_l','preset','gripper','fixed_tcp_demo'].includes(parseJson(raw)?.cmd))));
  }

  _abandonControl(session, reason, confirmed = false) {
    let abandoned = false;
    for (const [requestId, owner] of this.forwardedMotion) {
      if (session && owner !== session) continue;
      this.forwardedMotion.delete(requestId);
      sendJson(owner.browser, { type: 'error', request_id: requestId,
        code: confirmed ? 'motion_cancelled' : 'execution_uncertain', msg: reason });
      abandoned = true;
    }
    for (const owner of this.sessions) {
      if (session && owner !== session) continue;
      owner.queue.length = 0;
    }
    if (confirmed) this.controlUncertainAtMs = null;
    else if (abandoned) this.controlUncertainAtMs = Date.now();
  }

  _reconcileControl(message, session = null) {
    if (message?.request_id && (message.type === 'error'
        || message.type === 'command_status' && message.status === 'complete')) {
      this.forwardedMotion.delete(message.request_id);
    }
    if ((message?.type === 'software_stop' && message.complete === true
        && message.depowered === true) || message?.type === 'software_stop_complete') {
      this._abandonControl(null, 'Robot Service confirmed software stop', true);
    } else if (message?.type === 'connection' && message.connected === false) {
      this._abandonControl(session, 'Robot connection lost');
    } else if (message?.type === 'robot_state' && this.controlUncertainAtMs !== null
        && message.observedAtMs > this.controlUncertainAtMs) {
      const state = this.languageUpstream.getRobotState();
      if (state.connected && state.stateFresh && state.stateName === 'IDLE'
          && !state.motionActive) this.controlUncertainAtMs = null;
    }
  }

  _forward(session, message) {
    if (!this._mayForward(session,message)) {
      sendJson(session.browser,{type:'error',code:'grasp_active',request_id:message.request_id,
        msg:'抓取流程正在控制机械臂；可使用软件停止'});
      return false;
    }
    if (['servo','move_l','preset','gripper','fixed_tcp_demo'].includes(message.cmd)) {
      message = {...message,request_id:message.request_id || randomUUID()};
      this.forwardedMotion.set(message.request_id,session);
    }
    session.upstream.send(JSON.stringify(message));return true;
  }

  _flushQueued(session) {
    for (const raw of session.queue.splice(0)) this._forward(session,parseJson(raw));
  }

  attach(browser, {graspOwner=false} = {}) {
    const upstream = new WebSocket(this.robotWsUrl);
    const session = { browser, upstream, queue: [], graspOwner };
    this.sessions.add(session);

    sendJson(browser, {
      type: 'language_backend',
      ...this.languageUpstream.publicStatus(),
    });

    upstream.on('open', () => {
      this._flushQueued(session);
    });
    upstream.on('message', (data, isBinary) => {
      let payload = data;
      if (!isBinary) {
        const message = parseJson(data);
        this._reconcileControl(message, session);
        if (message?.type === 'config') {
          payload = JSON.stringify({
            ...message,
            language: this.languageRuntimeConfig(),
          });
        }
      }
      if (browser.readyState === WebSocket.OPEN) browser.send(payload, { binary: isBinary });
    });
    upstream.on('error', error => {
      sendJson(browser, {
        type: 'error',
        code: 'robot_service_unavailable',
        msg: `Robot Service unavailable: ${error.message}`,
      });
    });
    upstream.on('close', () => {
      this._abandonControl(session, 'Robot Service transport lost');
      if (browser.readyState === WebSocket.OPEN) {
        sendJson(browser, {
          type: 'connection',
          connected: false,
          reason: 'robot_service_disconnected',
        });
        // This browser transport is bound to one upstream stream. Recycle it
        // after service loss so clients perform a fresh read-only handshake;
        // never retain or replay queued actuator commands across a restart.
        browser.close(1012, 'robot_service_disconnected');
      }
    });

    browser.on('message', data => {
      const message = parseJson(data);
      if (!message) {
        sendJson(browser, {
          type: 'error',
          code: 'invalid_json',
          msg: 'Invalid JSON message',
        });
        return;
      }

      if (message.type === 'skill.candidate') {
        if (this.graspInterlock?.()?.active) {
          sendJson(browser, {type:'error',code:'grasp_active',msg:'抓取流程正在控制机械臂'});
          return;
        }
        const candidate = message.candidate || message.payload;
        let owners = this.languageCandidateOwners.get(browser);
        if (!owners) {
          owners = new Map();
          this.languageCandidateOwners.set(browser, owners);
        }
        if (candidate?.candidateId) owners.set(candidate.candidateId, candidate?.skill);
        if (candidate?.skill === DIRECTIONAL_SKILL) {
          this.directionalController.register(browser, candidate);
        } else {
          this.languageController.register(browser, candidate);
          if (candidate?.intent === 'end_effector.step') {
            this._previewCameraX(browser, candidate).catch(error => sendJson(browser, {
              type: 'skill.candidate.preview',
              candidateId: candidate.candidateId,
              traceId: candidate.traceId,
              ok: false,
              reason: error.message || '镜头 X 轴预览失败',
            }));
          }
        }
        return;
      }

      if (message.type === 'confirmation.decision') {
        if (this.graspInterlock?.()?.active) {
          sendJson(browser, {type:'error',code:'grasp_active',msg:'抓取流程正在控制机械臂'});
          return;
        }
        const owners = this.languageCandidateOwners.get(browser);
        const owner = owners?.get(message.candidateId);
        if (owner === DIRECTIONAL_SKILL) {
          this.directionalController.decide(browser, message);
        } else {
          this.languageController.decide(browser, message);
        }
        owners?.delete(message.candidateId);
        return;
      }

      const capabilityRequest=isCapabilityRequest(message);
      if (!capabilityRequest&&!ROBOT_COMMANDS.has(message.cmd)) {
        sendJson(browser, {
          type: 'error',
          code: 'service_unavailable',
          msg: `Command ${message?.cmd || '<missing>'} has not migrated to an online service`,
        });
        return;
      }
      if (!this._mayForward(session,message)) {
        sendJson(browser, {type:'error',code:'grasp_active',request_id:message.request_id,
          msg:'抓取流程正在控制机械臂；可使用软件停止'});
        return;
      }
      const payload = JSON.stringify(message);
      if (upstream.readyState === WebSocket.OPEN) this._forward(session,message);
      else if (upstream.readyState === WebSocket.CONNECTING) session.queue.push(payload);
      else {
        sendJson(browser, {
          type: 'error',
          code: 'robot_service_unavailable',
          msg: 'Robot Service is disconnected',
        });
      }
    });

    browser.on('close', () => {
      this._abandonControl(session, 'Browser disconnected');
      this.languageController.disconnect(browser);
      this.directionalController.disconnect(browser);
      this.languageCandidateOwners.delete(browser);
      this.sessions.delete(session);
      if (upstream.readyState < WebSocket.CLOSING) upstream.close();
    });
  }

  close() {
    this.languageUpstream.shutdown();
    for (const { browser, upstream } of this.sessions) {
      this.languageController.disconnect(browser);
      this.directionalController.disconnect(browser);
      browser.terminate();
      upstream.terminate();
    }
    this.languageCandidateOwners.clear();
    this.sessions.clear();
  }
}

module.exports = { ROBOT_COMMANDS, RobotProxy };
