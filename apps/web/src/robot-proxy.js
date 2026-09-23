'use strict';

const { WebSocket } = require('ws');
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
  'preset',
  'gripper',
  'software_stop',
  'estop',
  'ping',
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
    this.robotWsUrl = robotWsUrl;
    this.languageConfig = languageConfig;
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
      manualControlBackend: 'formal-3000-upstream',
      upstream: this.languageUpstream.publicStatus(),
    };
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
        }
        return;
      }

      if (message.type === 'confirmation.decision') {
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

      if (!ROBOT_COMMANDS.has(message.cmd)) {
        sendJson(browser, {
          type: 'error',
          code: 'service_unavailable',
          msg: `Command ${message?.cmd || '<missing>'} has not migrated to an online service`,
        });
        return;
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
