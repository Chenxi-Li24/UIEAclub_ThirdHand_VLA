'use strict';

const { MeituanExecutor, MEITUAN_SKILL } = require('../../../skills/manipulation/meituan_battery_pnp/src/executor');
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
  'gripper',
  'software_stop',
  'estop',
  'ping',
]);

const READ_ONLY_ROBOT_COMMANDS = new Set([
  'status', 'ping', 'preview_ik', 'software_stop', 'estop',
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

class RobotProxy {
  constructor(robotWsUrl, languageConfig = {}) {
    languageConfig = { ...languageConfig, realControlEnabled: false,
      directionalRealControlEnabled: false, cameraProbeEnabled: false,
      cameraRealControlEnabled: false };
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

    this.meituanExecutor = languageConfig.meituanEnabled ? new MeituanExecutor({
      ...languageConfig.meituanExecutorOptions,
      bridge: this.languageUpstream,
      enabled: languageConfig.realControlEnabled,
      modelFiles: languageConfig.meituanModelFiles,
    }) : null;
    this.meituanBrowser = null;
    if (this.meituanExecutor) this.skillExecutors.register(MEITUAN_SKILL, this.meituanExecutor);

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
      sendRobot: command => this.languageUpstream.send(command),
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
      robotControlReadOnly: true,
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

  async _previewMeituan(browser, candidate) {
    const result = this.meituanExecutor
      ? await this.meituanExecutor.prepare(candidate)
      : { ok: false, reason: '仅1034提供美团整条路线执行' };
    const pending = this.languageController.sessions.get(browser)?.get(candidate.candidateId);
    if (!pending || pending.candidate.traceId !== candidate.traceId) {
      this.meituanExecutor?.discard(candidate.candidateId);
      return;
    }
    sendJson(browser, { type: 'skill.candidate.preview',
      candidateId: candidate.candidateId, traceId: candidate.traceId, ...result });
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

  attach(browser) {
    const upstream = new WebSocket(this.robotWsUrl);
    const session = { browser, upstream, queue: [] };
    this.sessions.add(session);

    sendJson(browser, {
      type: 'language_backend',
      ...this.languageUpstream.publicStatus(),
    });

    upstream.on('open', () => {
      for (const payload of session.queue.splice(0)) upstream.send(payload);
    });
    upstream.on('message', (data, isBinary) => {
      let payload = data;
      if (!isBinary) {
        const message = parseJson(data);
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
      if (browser.readyState === WebSocket.OPEN) {
        sendJson(browser, {
          type: 'connection',
          connected: false,
          reason: 'robot_service_disconnected',
        });
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
        const candidate = message.candidate || message.payload;
        if (this.meituanExecutor?.isActive()) {
          if (candidate?.intent === 'safety.stop.request') this.meituanExecutor.cancel('用户请求停止');
          else {
            sendJson(browser, { type: 'skill.candidate.rejected',
              candidateId: candidate?.candidateId, traceId: candidate?.traceId,
              reason: '美团整条路线正在执行，请先停止或等待完成' });
            return;
          }
        }
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
          if (candidate?.skill === MEITUAN_SKILL) {
            this._previewMeituan(browser, candidate).catch(error => sendJson(browser, {
              type: 'skill.candidate.preview', candidateId: candidate.candidateId,
              traceId: candidate.traceId, ok: false, reason: error.message,
            }));
          }
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
        if (message.decision === 'approve') {
          sendJson(browser, { type: 'skill.result', candidateId: message.candidateId,
            traceId: message.traceId, success: false, status: 'blocked',
            code: 'meituan_motion_not_enabled',
            message: 'Meituan motion is not enabled in this migration' });
          return;
        }
        const owners = this.languageCandidateOwners.get(browser);
        const owner = owners?.get(message.candidateId);
        if (this.meituanExecutor?.isActive() && message.decision === 'approve') {
          sendJson(browser, { type: 'skill.result', candidateId: message.candidateId,
            traceId: message.traceId, success: false, status: 'blocked',
            message: '美团路线正在执行，禁止重叠动作' });
          return;
        }
        if (owner === MEITUAN_SKILL) {
          if (message.decision === 'approve') this.meituanBrowser = browser;
          else this.meituanExecutor?.discard(message.candidateId);
        }
        if (owner === DIRECTIONAL_SKILL) {
          this.directionalController.decide(browser, message);
        } else {
          this.languageController.decide(browser, message);
        }
        owners?.delete(message.candidateId);
        return;
      }

      if (!ROBOT_COMMANDS.has(message.cmd)) {
        sendJson(browser, {
          type: 'error',
          code: 'service_unavailable',
          msg: `Command ${message?.cmd || '<missing>'} has not migrated to an online service`,
        });
        return;
      }
      if (!READ_ONLY_ROBOT_COMMANDS.has(message.cmd)) {
        sendJson(browser, { type: 'error', code: 'meituan_motion_not_enabled',
          request_id: message.request_id,
          msg: 'Meituan motion is not enabled in this migration' });
        return;
      }
      if (this.meituanExecutor?.isActive()) {
        if (['software_stop', 'estop', 'disconnect'].includes(message.cmd)) {
          this.meituanExecutor.cancel('用户停止或断开控制');
        } else if (!['status', 'ping'].includes(message.cmd)) {
          sendJson(browser, { type: 'error', code: 'meituan_route_active',
            msg: '美团路线正在执行，其他动作被阻止；可使用软件停止' });
          return;
        }
      }
      const payload = JSON.stringify(message);
      if (upstream.readyState === WebSocket.OPEN) upstream.send(payload);
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
      if (this.meituanBrowser === browser) this.meituanExecutor?.cancel('控制页面断开');
      for (const id of this.languageCandidateOwners.get(browser)?.keys() || []) {
        this.meituanExecutor?.discard(id);
      }
      this.languageController.disconnect(browser);
      this.directionalController.disconnect(browser);
      this.languageCandidateOwners.delete(browser);
      this.sessions.delete(session);
      if (upstream.readyState < WebSocket.CLOSING) upstream.close();
    });
  }

  close() {
    this.meituanExecutor?.cancel('1034 网关关闭');
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
