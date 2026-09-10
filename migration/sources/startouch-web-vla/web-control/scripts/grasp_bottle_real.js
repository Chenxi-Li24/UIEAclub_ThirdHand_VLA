#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const { spawn } = require('node:child_process');
const { EventEmitter } = require('node:events');
const { randomUUID } = require('node:crypto');
const { GraspController } = require('../server/grasp-controller');
const { buildSupervisedPlan, motionDuration, verifyHold } = require('../server/supervised-grasp-plan');

const DEFAULT_BRIDGE_ROOT = '/home/nieqingcao/TH-Fanxy';
const DEFAULT_VISION_ROOT = '/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill';
const DEFAULT_VISION_PYTHON = '/home/nieqingcao/miniconda3/envs/thirdhand-groundedsam2/bin/python';
const MAX_ANCHOR_AGE_MS = 300000;
const MAX_REFERENCE_PLAN_XY_DRIFT_M = 0.01;
const HELP = `Usage:
  node web-control/scripts/grasp_bottle_real.js --simulate --settings <json-or-file>
  node web-control/scripts/grasp_bottle_real.js --live --settings <json-or-file> [options]

Options:
  --bridge-root PATH   Startouch bridge repository (default: ${DEFAULT_BRIDGE_ROOT})
  --vision-root PATH   PinZiZhuaQuSkill root (default: ${DEFAULT_VISION_ROOT})
  --vision-python PATH Python with the vision runtime

Commands (each is an explicit operator checkpoint):
  connect | observe | home | open | hover | descend | close | lift
  confirm success | confirm failure <category> | new trial [empty]
  status | stop | quit supported

Failure categories: detection depth calibration hover descend grasp slip robot_command

No argument only prints this help. --simulate never loads the Startouch SDK or camera.`;

const finiteVector = (value, size = 3) =>
  Array.isArray(value) && value.length === size && value.every(Number.isFinite);

const FAILURE_CATEGORIES = new Set([
  'detection', 'depth', 'calibration', 'hover', 'descend', 'grasp', 'slip', 'robot_command',
]);

function normalizeFailureCategory(value) {
  const normalized = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  return FAILURE_CATEGORIES.has(normalized) ? normalized : null;
}

function failureCategory(reason, phase) {
  const value = String(reason || '').toLowerCase();
  if (/slip|dropped/.test(value)) return 'slip';
  if (/calibration|handeye|base_transform/.test(value)) return 'calibration';
  if (/depth|width|geometry|pose_invalid|position_invalid|position_shifted|base_candidate|grasp_height/.test(value)) {
    return 'depth';
  }
  if (/target_lost|target_identity|target_ordinal|target_stale|target_timestamp|observer_|camera_/.test(value)) {
    return 'detection';
  }
  if (/robot|bridge|command|cartesian|workspace|home_|gripper_open|joint|duration|disconnect|connection|arm_motion|continuation|segment|endpoint/.test(value)) {
    return 'robot_command';
  }
  if (phase === 'hover') return 'hover';
  if (phase === 'descend') return 'descend';
  if (['close', 'lift', 'holding'].includes(phase)) return 'grasp';
  return 'robot_command';
}
const radians = degrees => degrees.map(value => value * Math.PI / 180);
const distance = (a, b) => Math.hypot(...a.map((value, index) => value - b[index]));
const angleDistance = (a, b) => Math.hypot(...a.map((value, index) =>
  Math.atan2(Math.sin(value - b[index]), Math.cos(value - b[index]))));

function readSettings(value) {
  if (!value) throw new Error('--settings is required');
  const text = value.trim().startsWith('{') ? value : fs.readFileSync(path.resolve(value), 'utf8');
  return JSON.parse(text);
}

function parseArgs(argv) {
  if (!Array.isArray(argv)) throw new TypeError('arguments_invalid');
  if (argv.length === 0 || argv.includes('--help') || argv.includes('-h')) return { mode: 'help' };
  let mode = null;
  let settingsValue = null;
  let bridgeRoot = DEFAULT_BRIDGE_ROOT;
  let visionRoot = DEFAULT_VISION_ROOT;
  let visionPython = DEFAULT_VISION_PYTHON;
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (item === '--live' || item === '--simulate') {
      if (mode) throw new Error('choose exactly one of --live or --simulate');
      mode = item.slice(2);
    } else if (['--settings', '--bridge-root', '--vision-root', '--vision-python'].includes(item)) {
      const next = argv[++index];
      if (!next) throw new Error(`${item} requires a value`);
      if (item === '--settings') settingsValue = next;
      if (item === '--bridge-root') bridgeRoot = path.resolve(next);
      if (item === '--vision-root') visionRoot = path.resolve(next);
      if (item === '--vision-python') visionPython = path.resolve(next);
    } else {
      throw new Error(`unknown argument: ${item}`);
    }
  }
  if (!mode) throw new Error('choose --live or --simulate');
  return { mode, settings: readSettings(settingsValue), bridgeRoot, visionRoot, visionPython };
}

function normalizeObservation(raw, expectedWidthM = null) {
  const calibrationId = raw?.handeye?.calibration_id || raw?.calibration_id || null;
  const timestampValid = Number.isFinite(raw?.observed_at_ms) && Number.isFinite(raw?.robot_state_ts);
  const poseValid = finiteVector(raw?.pixel_uv, 2) && finiteVector(raw?.camera_xyz_m) &&
    finiteVector(raw?.base_xyz_m);
  const width = Number.isFinite(raw?.width_m) ? raw.width_m : expectedWidthM;
  const baseValid = raw?.supervised_base_candidate_valid === true;
  const locked = raw?.track_state === 'locked' && typeof raw?.target_id === 'string';
  const valid = raw?.event === 'bottle_observation' && raw?.valid === true && locked &&
    baseValid && timestampValid && poseValid && Number.isFinite(width);
  return {
    ...raw,
    valid,
    reason: valid ? null : (raw?.reason || (!locked ? 'target_lost' :
      !baseValid ? 'base_candidate_invalid' : !timestampValid ? 'target_timestamp_invalid' :
        !poseValid ? 'target_pose_invalid' : 'grasp_width_invalid')),
    calibration_id: calibrationId,
    width_m: width,
    physical_validation: raw?.handeye?.physically_validated === true ? 'passed' : 'pending',
  };
}

function validateSettings(settings) {
  if (!settings || typeof settings !== 'object') throw new Error('settings_invalid');
  settings.targetOrdinal ??= 2;
  settings.maxObservationAgeMs ??= 300;
  settings.maxCameraWatchdogAgeMs ??= 500;
  settings.maxRobotAgeMs ??= 500;
  settings.maxSpeedMps ??= 0.02;
  settings.maxAngularSpeedRadS ??= 0.30;
  settings.positionToleranceM ??= 0.008;
  settings.orientationToleranceRad ??= 0.12;
  settings.commandTimeoutGraceMs ??= 5000;
  settings.gripperCommandTimeoutMs ??= 5000;
  settings.safeTransitZM ??= settings.safeTransitZ;
  if (!Number.isSafeInteger(settings.targetOrdinal) || settings.targetOrdinal < 1 ||
      !finiteVector(settings.eulerRad) || !finiteVector(settings.graspOffsetM) ||
      !finiteVector(settings.homeJointsDeg, 6) || !finiteVector(settings.homeTcpM) ||
      !Number.isFinite(settings.safeTransitZM) ||
      !Number.isFinite(settings.maxObservationAgeMs) || settings.maxObservationAgeMs <= 0 ||
      settings.maxObservationAgeMs > 300 ||
      !Number.isFinite(settings.maxCameraWatchdogAgeMs) ||
      settings.maxCameraWatchdogAgeMs < settings.maxObservationAgeMs ||
      settings.maxCameraWatchdogAgeMs > 500 ||
      !Number.isFinite(settings.maxRobotAgeMs) || settings.maxRobotAgeMs <= 0 ||
      settings.maxRobotAgeMs > 500 ||
      !Number.isFinite(settings.commandTimeoutGraceMs) || settings.commandTimeoutGraceMs < 1000 ||
      settings.commandTimeoutGraceMs > 5000 ||
      !Number.isFinite(settings.gripperCommandTimeoutMs) || settings.gripperCommandTimeoutMs < 3000 ||
      settings.gripperCommandTimeoutMs > 5000 ||
      !Number.isFinite(settings.maxSpeedMps) || settings.maxSpeedMps <= 0 ||
      settings.maxSpeedMps > 0.02 || !Number.isFinite(settings.maxAngularSpeedRadS) ||
      settings.maxAngularSpeedRadS <= 0 || settings.maxAngularSpeedRadS > 0.30) {
    throw new Error('settings_invalid');
  }
  const bounds = ['x', 'y', 'z'].map(axis => settings.workspace?.[axis]);
  if (bounds.some(bound => !finiteVector(bound, 2) || bound[0] >= bound[1])) {
    throw new Error('workspace_invalid');
  }
  const within = point => point.every((value, index) =>
    value >= bounds[index][0] && value <= bounds[index][1]);
  if (!within(settings.homeTcpM) || !within([settings.homeTcpM[0], settings.homeTcpM[1], settings.safeTransitZM])) {
    throw new Error('home_or_safe_transit_outside_workspace');
  }
  if (settings.graspHeightBaseM !== undefined &&
      (!Number.isFinite(settings.graspHeightBaseM) ||
       settings.graspHeightBaseM < bounds[2][0] || settings.graspHeightBaseM > bounds[2][1])) {
    throw new Error('grasp_height_base_invalid');
  }
  if (settings.graspHeightBaseM !== undefined && settings.fixedGraspBaseZM !== undefined) {
    throw new Error('grasp_height_policy_conflict');
  }
  if (settings.observationHeightBaseM !== undefined &&
      (!Number.isFinite(settings.observationHeightBaseM) ||
       settings.observationHeightBaseM < bounds[2][0] || settings.observationHeightBaseM > bounds[2][1])) {
    throw new Error('observation_height_base_invalid');
  }
  if (settings.observationHeightBaseM !== undefined && settings.graspHeightBaseM !== undefined) {
    throw new Error('observation_height_policy_conflict');
  }
  if (settings.bottleDiameterM !== undefined &&
      (!Number.isFinite(settings.bottleDiameterM) || settings.bottleDiameterM <= 0 ||
       settings.bottleDiameterM > 0.072)) {
    throw new Error('bottle_diameter_invalid');
  }
  if (settings.observationHeightBaseM !== undefined && settings.bottleDiameterM === undefined) {
    throw new Error('bottle_diameter_required');
  }
  if (settings.observerOverlayFile !== undefined &&
      (typeof settings.observerOverlayFile !== 'string' ||
       !path.isAbsolute(settings.observerOverlayFile))) {
    throw new Error('observer_overlay_file_invalid');
  }
  if (settings.fixedGraspBaseZM !== undefined &&
      (!Number.isFinite(settings.fixedGraspBaseZM) ||
       settings.fixedGraspBaseZM < bounds[2][0] || settings.fixedGraspBaseZM > bounds[2][1])) {
    throw new Error('fixed_grasp_base_z_invalid');
  }
  return settings;
}

class OfflineBridge extends EventEmitter {
  constructor(settings, nowMs = Date.now) {
    super();
    this.settings = settings;
    this.nowMs = nowMs;
    this.position = [...settings.homeTcpM];
    this.euler = [0, 0, 0];
    this.joints = radians(settings.homeJointsDeg);
    this.connected = false;
  }
  start() {
    setImmediate(() => {
      this.emit('bridge_ready', { type: 'bridge_ready' });
    });
  }
  send(command) {
    setImmediate(() => {
      if (command.cmd === 'connect') {
        this.connected = true;
        this.emit('connection', { type: 'connection', connected: true, simulated: true });
        return this._state();
      }
      if (command.cmd === 'get_state') return this._state();
      if (command.cmd === 'move_l') {
        this.emit('motion_state', { type: 'motion_state', state: 'MOVING', request_id: command.request_id });
        this.position = [...command.position];
        this.euler = [...command.euler];
        this.emit('command_complete', { type: 'command_complete', command: 'move_l',
          request_id: command.request_id, reached: true, position_error_m: 0,
          orientation_error_rad: 0 });
        this.emit('motion_state', { type: 'motion_state', state: 'IDLE', request_id: command.request_id });
        return this._state();
      }
      if (command.cmd === 'move_joint') {
        this.joints = [...command.joints_rad];
        this.emit('command_complete', { type: 'command_complete', command: 'move_joint',
          request_id: command.request_id });
        return this._state();
      }
      if (command.cmd === 'gripper') {
        const closing = command.position === 0;
        this.emit('command_complete', { type: 'command_complete', command: 'gripper',
          request_id: command.request_id, reached: !closing, moved: true,
          actual_position: closing ? 0.5 : 1.0 });
      }
    });
    return true;
  }
  softwareStop() {
    this.connected = false;
    this.connectRequested = false;
    this.connectSent = false;
    setImmediate(() => this.emit('connection', { connected: false, reason: 'software_stop' }));
    return true;
  }
  shutdown() { this.connected = false; }
  _state() {
    this.emit('robot_state', { type: 'robot_state', joints_rad: [...this.joints],
      tcp_position_m: [...this.position], tcp_euler_rad: [...this.euler], state: 'IDLE' });
  }
}

class SupervisedGraspCli {
  constructor({ bridge, settings, nowMs = Date.now, writeEvent, writeResult, writePose,
    setTimer = setInterval, clearTimer = clearInterval, startObserver = null }) {
    this.settings = validateSettings({ ...settings });
    this.bridge = bridge;
    this.nowMs = nowMs;
    this.writeEvent = writeEvent || (event => process.stdout.write(`${JSON.stringify(event)}\n`));
    this.writeResult = writeResult || (() => {});
    this.writePose = writePose || (() => {});
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.startObserver = startObserver;
    this.connected = false;
    this.motionActive = false;
    this.latestRobot = null;
    this.stationarySinceMs = null;
    this.latestObservation = null;
    this.latestGuardFrame = null;
    this.latestProjectionGuard = null;
    this.nearfieldAuthorization = null;
    this.supervisedAnchor = null;
    this.lockedTargetId = this.settings.targetId || null;
    this.lastStageFrameId = null;
    this.pending = null;
    this.homeAwaitingState = false;
    this.homeVerified = false;
    this.gripperOpen = false;
    this.holdingObjectPossible = false;
    this.contact = false;
    this.holdStartedAtMs = null;
    this.descendMeasuredZ = null;
    this.lastMotionCompletedAtMs = null;
    this.lastActionCompletedAtMs = null;
    this.resultRecorded = false;
    this.failurePhase = null;
    this.lastCameraCaptureMs = null;
    this.freshEvidenceAfterMs = null;
    this.observerProcess = null;
    this.poseTimer = null;
    this.quitting = false;
    this.trialId = randomUUID();
    this.controller = new GraspController({
      sendRobot: (command, phase) => this._sendControllerCommand(command, phase),
      authorizePlan: () => this._authorizeObservation(),
      canContinue: () => this._continuationGate(),
    });
    this.controller.on('status', status => {
      this._event('grasp_status', status);
      if (status.phase === 'aborted' && this.pending?.kind === 'controller') {
        if (this.pending.awaitingGuard && !this.motionActive) {
          this._event('completed_segment_abort_cleared', { reason: status.reason,
            phase: this.pending.phase, further_segments_sent: false });
          this.pending = null;
        } else {
          this.pending.cancelAfterCurrent = true;
          this._event('motion_cancel_latched', {
            reason: status.reason,
            motion_stop_mode: 'after_current_bounded_segment',
            note: 'Startouch exposes no supported cancel-and-hold; no later segment or grasp phase will be sent.',
          });
        }
      }
      if (status.phase === 'aborted') this._recordFailure(status.reason || 'grasp_aborted');
      this._writePoseSnapshot();
    });
    this._bindBridge();
  }

  snapshot() { return this.controller.snapshot(); }

  _event(type, detail = {}) {
    this.writeEvent({ ts: this.nowMs(), type, trial_id: this.trialId, ...detail });
  }

  _bindBridge() {
    this.bridge.on('bridge_ready', event => {
      this._event('bridge_ready', event);
      if (!this.connectRequested || this.connectSent || this.quitting) return;
      this.connectSent = true;
      if (!this.bridge.send({ cmd: 'connect' })) {
        this.failurePhase = 'connect';
        this._recordFailure('bridge_connect_rejected');
        this.bridge.shutdown();
        return;
      }
      this._event('bridge_connect_sent', { one_shot: true });
    });
    this.bridge.on('connection', event => {
      this.connected = event.connected === true;
      this._event('bridge_connection', event);
      if (!this.connected && !this.quitting && this.controller.snapshot().phase !== 'idle') {
        this.controller.cancel(event.reason || 'robot_disconnected');
      }
      if (!this.connected && this.connectRequested && !this.quitting) {
        this._event('bridge_reconnect_disabled', { reason: event.reason || 'connection_lost' });
        this.bridge.shutdown();
      }
    });
    this.bridge.on('motion_state', event => {
      const moving = event.state === 'MOVING';
      if (moving && !this.motionActive) this.stationarySinceMs = null;
      if (!moving && this.motionActive) this.stationarySinceMs = this.nowMs();
      this.motionActive = moving;
      this._writePoseSnapshot();
      this._event('robot_motion', event);
      if (!moving) this._resumeAfterSegmentGuard();
    });
    this.bridge.on('robot_state', event => this._robotState(event));
    this.bridge.on('command_complete', event => this._commandComplete(event));
    this.bridge.on('error', event => this._robotFailure(event.message || 'robot_error', event));
    this.bridge.on('bridge_error', event => this._robotFailure(event.message || 'bridge_error', event));
    this.bridge.on('log', event => this._event('bridge_log', event));
  }

  _robotState(event) {
    const position = event.tcp_position_m || event.tcp_position;
    const euler = event.tcp_euler_rad || event.tcp_euler;
    const joints = event.joints_rad || event.joints;
    if (!finiteVector(position) || !finiteVector(euler)) {
      this._robotFailure('robot_pose_invalid', event);
      return;
    }
    const now = this.nowMs();
    const sampleTs = event.ts === undefined ? now : Number(event.ts);
    if (!Number.isFinite(sampleTs) || sampleTs > now || now - sampleTs > this.settings.maxRobotAgeMs) {
      this._robotFailure('robot_state_timestamp_invalid', event);
      return;
    }
    if (!this.motionActive && this.stationarySinceMs === null) this.stationarySinceMs = now;
    this.latestRobot = { position: [...position], euler: [...euler],
      joints: finiteVector(joints, 6) ? [...joints] : null, receivedAtMs: sampleTs };
    this._writePoseSnapshot();
    if (this.homeAwaitingState) this._verifyHomeState();
  }

  _writePoseSnapshot() {
    if (!this.latestRobot) return;
    this.writePose({ pose_frame: 'sdk_tool', tcp_position_m: [...this.latestRobot.position],
      tcp_euler_rad: [...this.latestRobot.euler], ts: this.latestRobot.receivedAtMs,
      stationary: !this.motionActive, stationary_since_ms: this.stationarySinceMs,
      trial_id: this.trialId, controller_phase: this._poseControllerPhase(),
      controller_state_phase: this.snapshot().phase,
      pending_phase: this.pending?.kind === 'controller' ? this.pending.phase : null,
      supervised_anchor: this.supervisedAnchor ? JSON.parse(JSON.stringify(this.supervisedAnchor)) : null });
  }

  _poseControllerPhase() {
    if (this.pending?.kind === 'controller') return this.pending.phase;
    const state = this.snapshot();
    if (state.phase === 'preview_ready') {
      return state.nextPhase === 'descend' ? 'hover' : state.nextPhase === 'close' ? 'descend' :
        state.nextPhase === 'lift' ? 'close' : 'preview_ready';
    }
    return state.phase;
  }

  _authorizeObservation() {
    if (this.supervisedAnchor) {
      const gate = this._continuationGate();
      if (!gate.approved) return gate;
      if (this.nowMs() - this.supervisedAnchor.approved_at_ms > MAX_ANCHOR_AGE_MS) {
        return { approved: false, reason: 'anchor_stale' };
      }
      if (this.nearfieldAuthorization?.initialAnchor === true &&
          this.latestObservation?.frame_id === this.supervisedAnchor.reference.frame_id &&
          this.nowMs() - this.supervisedAnchor.reference.observed_at_ms <=
            this.settings.maxObservationAgeMs) return this.nearfieldAuthorization;
      const invalid = this._staticProjectionGuardFailure(this.latestProjectionGuard);
      if (invalid) return { approved: false, reason: invalid };
      return this.nearfieldAuthorization || { approved: false, reason: 'projection_guard_required' };
    }
    const observation = this.latestObservation;
    const gate = this._continuationGate();
    if (!gate.approved) return gate;
    if (!observation?.valid) return { approved: false, reason: observation?.reason || 'target_lost' };
    const planSettings = { ...this.settings, targetId: this.lockedTargetId };
    const checked = buildSupervisedPlan(observation, planSettings, this.nowMs());
    if (!checked.approved) return checked;
    return checked;
  }

  _continuationGate() {
    if (!this.connected) return { approved: false, reason: 'robot_disconnected' };
    if (this.motionActive || this.pending) return { approved: false, reason: 'arm_motion_active' };
    if (!this.latestRobot || this.nowMs() - this.latestRobot.receivedAtMs > this.settings.maxRobotAgeMs) {
      return { approved: false, reason: 'robot_state_stale' };
    }
    return { approved: true };
  }

  observerLine(line) {
    let raw;
    try { raw = JSON.parse(line); } catch {
      this._invalidateTarget('observer_json_invalid');
      return;
    }
    if (raw.event === 'bottle_projection_guard') {
      this._projectionGuardLine(raw);
      return;
    }
    if (raw.event !== 'bottle_observation') {
      if (raw.valid === false) this._invalidateTarget(raw.reason || 'observer_stream_invalid');
      return;
    }
    if (this.supervisedAnchor && ['hover', 'descend', 'close', 'lift', 'holding']
      .includes(this._poseControllerPhase())) {
      this._event('legacy_observation_ignored_nearfield', { frame_id: raw.frame_id,
        controller_phase: this._poseControllerPhase() });
      return;
    }
    const cameraFailed = raw.camera_observation_valid !== true || raw.track_state !== 'locked' ||
      !finiteVector(raw.camera_xyz_m) || !finiteVector(raw.pixel_uv, 2);
    if (cameraFailed) {
      this._invalidateTarget(raw.reason || 'target_lost');
      return;
    }
    const captureMs = raw.observed_at_ms;
    const calibrationId = raw?.handeye?.calibration_id || raw?.calibration_id;
    if (!Number.isFinite(captureMs) || captureMs > this.nowMs() ||
        this.nowMs() - captureMs > this.settings.maxObservationAgeMs) {
      this._invalidateTarget('target_stale');
      return;
    }
    if (this.lockedTargetId && raw.target_id !== this.lockedTargetId) {
      this._invalidateTarget('target_identity_changed');
      return;
    }
    if (this.controller.state.calibrationId && calibrationId !== this.controller.state.calibrationId) {
      this._invalidateTarget('calibration_changed');
      return;
    }
    if (Number.isFinite(this.freshEvidenceAfterMs) && captureMs < this.freshEvidenceAfterMs) {
      this._event('observer_pretrial_frame_ignored', { frame_id: raw.frame_id,
        observed_at_ms: captureMs, fresh_evidence_after_ms: this.freshEvidenceAfterMs });
      return;
    }
    this.lastCameraCaptureMs = captureMs;
    const poseBlockers = Array.isArray(raw.robot_pose_blockers) ? raw.robot_pose_blockers : [];
    const capturePredatesStationary = Number.isFinite(this.stationarySinceMs) &&
      captureMs < this.stationarySinceMs;
    const onlyMotionPoseBlockers = (this.motionActive || capturePredatesStationary) &&
      this.pending?.kind === 'controller' && poseBlockers.length > 0 &&
      poseBlockers.every(reason => ['pose_not_stationary', 'robot_pose_stale',
        'pose_does_not_cover_frame_capture'].includes(reason));
    if (onlyMotionPoseBlockers) {
      this._event('observer_motion_frame', { frame_id: raw.frame_id,
        target_id: raw.target_id, robot_pose_blockers: poseBlockers });
      this._resumeAfterSegmentGuard();
      return;
    }
    const observation = normalizeObservation(raw);
    if (!observation.valid) {
      this._invalidateTarget(observation.reason);
      return;
    }
    if (!this.lockedTargetId) {
      if (raw.requested_ordinal !== this.settings.targetOrdinal) {
        this._invalidateTarget('target_ordinal_mismatch');
        return;
      }
      this.lockedTargetId = observation.target_id;
      this._event('target_identity_locked', { target_ordinal: this.settings.targetOrdinal,
        target_id: this.lockedTargetId });
    }
    if (observation.target_id !== this.lockedTargetId) {
      this._invalidateTarget('target_identity_changed');
      return;
    }
    this.latestObservation = observation;
    this.latestGuardFrame = raw;
    const checked = buildSupervisedPlan(observation,
      { ...this.settings, targetId: this.lockedTargetId }, this.nowMs());
    if (!checked.approved) {
      this._invalidateTarget(checked.reason);
      return;
    }
    this.controller.updateTarget({ ...checked.plan, observation,
      graspM: checked.plan.graspM, pregraspM: checked.plan.pregraspM,
      retreatM: checked.plan.retreatM, yawRad: checked.plan.yawRad });
    if (!['idle', 'aborted', 'holding'].includes(this.snapshot().phase) &&
        this.controller.state.plan &&
        distance(checked.plan.graspM, this.controller.state.plan.graspM) > 0.02) {
      this.failurePhase = this.pending?.phase || this._poseControllerPhase();
      this.controller.cancel('target_position_shifted');
      return;
    }
    this._event('observation_accepted', this._preview(checked.plan));
    this._resumeAfterSegmentGuard();
  }

  _projectionGuardLine(raw) {
    const anchor = this.supervisedAnchor;
    if (!anchor) return this._invalidateTarget('anchor_missing');
    const captureMs = raw.observed_at_ms;
    const inMotion = this.motionActive || (this.pending?.kind === 'controller' &&
      !this.pending.awaitingGuard);
    const allowedAgeMs = inMotion ? this.settings.maxCameraWatchdogAgeMs :
      this.settings.maxObservationAgeMs;
    const commonFailure = raw.trial_id !== this.trialId ? 'trial_mismatch' :
      raw.anchor_id !== anchor.anchor_id ? 'anchor_mismatch' :
        raw.target_id !== anchor.target_id ? 'target_identity_changed' :
          raw.calibration_id !== anchor.calibration_id ? 'calibration_changed' :
            !Number.isFinite(captureMs) || captureMs > this.nowMs() ||
              this.nowMs() - captureMs > allowedAgeMs ? 'target_stale' :
              this.nowMs() - anchor.approved_at_ms > MAX_ANCHOR_AGE_MS ? 'anchor_stale' : null;
    if (commonFailure) return this._invalidateTarget(commonFailure);
    this.lastCameraCaptureMs = captureMs;
    if (raw.rgb_observation_valid !== true) {
      return this._invalidateTarget(raw.guard_blockers?.[0] || 'target_lost');
    }
    if (inMotion) {
      this.latestGuardFrame = raw;
      this._event('nearfield_rgb_motion_frame', { frame_id: raw.frame_id,
        anchor_id: raw.anchor_id, target_id: raw.target_id });
      return;
    }
    const poseBlockers = Array.isArray(raw.robot_pose_blockers) ? raw.robot_pose_blockers : [];
    const guardBlockers = Array.isArray(raw.guard_blockers) ? raw.guard_blockers : [];
    const capturePredatesStationary = Number.isFinite(this.stationarySinceMs) &&
      captureMs < this.stationarySinceMs;
    const expectedOldFrameBlockers = this.pending?.kind === 'controller' &&
      this.pending.awaitingGuard && capturePredatesStationary &&
      [...poseBlockers, ...guardBlockers].every(reason => ['pose_unavailable',
        'pose_not_stationary', 'robot_pose_stale', 'pose_does_not_cover_frame_capture'].includes(reason));
    const expectedFinalOldFrame = !this.pending && capturePredatesStationary &&
      Number.isFinite(this.lastMotionCompletedAtMs) &&
      ['preview_ready', 'holding'].includes(this.snapshot().phase) &&
      [...poseBlockers, ...guardBlockers].every(reason => ['pose_unavailable',
        'pose_not_stationary', 'robot_pose_stale', 'pose_does_not_cover_frame_capture'].includes(reason));
    if (expectedOldFrameBlockers || expectedFinalOldFrame) {
      this.latestGuardFrame = raw;
      this._event('projection_guard_wait_old_frame', { frame_id: raw.frame_id,
        observed_at_ms: captureMs, stationary_since_ms: this.stationarySinceMs });
      return;
    }
    if (raw.projection_guard_valid !== true || poseBlockers.length || guardBlockers.length ||
        !finiteVector(raw.expected_anchor_base_xyz_m) ||
        !finiteVector(raw.projected_anchor_camera_xyz_m) || !finiteVector(raw.pixel_uv, 2)) {
      return this._invalidateTarget(guardBlockers[0] || poseBlockers[0] || 'projection_guard_invalid');
    }
    if (!this.latestRobot || !Number.isFinite(raw.robot_state_ts) ||
        this.nowMs() - raw.robot_state_ts > this.settings.maxRobotAgeMs ||
        raw.robot_state_ts < captureMs || raw.robot_state_ts > this.latestRobot.receivedAtMs ||
        !Number.isFinite(this.stationarySinceMs) || captureMs < this.stationarySinceMs) {
      return this._invalidateTarget('projection_pose_not_fresh');
    }
    const expected = this._expectedAnchorBase();
    if (!expected || distance(raw.expected_anchor_base_xyz_m, expected) > 0.001) {
      return this._invalidateTarget('projected_anchor_mismatch');
    }
    this.latestProjectionGuard = raw;
    this.latestGuardFrame = raw;
    this.nearfieldAuthorization = { approved: true,
      plan: this._frozenGuardPlan(raw.observed_at_ms, raw.frame_id) };
    this.controller.updateTarget(this.nearfieldAuthorization.plan);
    this._event('projection_guard_accepted', { frame_id: raw.frame_id,
      anchor_id: raw.anchor_id, expected_anchor_base_xyz_m: expected });
    this._resumeAfterSegmentGuard();
  }

  _staticProjectionGuardFailure(raw) {
    if (!raw || raw.projection_guard_valid !== true || raw.rgb_observation_valid !== true) {
      return 'projection_guard_required';
    }
    if (raw.trial_id !== this.trialId) return 'trial_mismatch';
    if (raw.anchor_id !== this.supervisedAnchor.anchor_id) return 'anchor_mismatch';
    if (raw.target_id !== this.supervisedAnchor.target_id) return 'target_identity_changed';
    if (raw.calibration_id !== this.supervisedAnchor.calibration_id) return 'calibration_changed';
    if (!Number.isFinite(raw.observed_at_ms) || raw.observed_at_ms > this.nowMs() ||
        this.nowMs() - raw.observed_at_ms > this.settings.maxObservationAgeMs) return 'target_stale';
    if (!Number.isFinite(raw.robot_state_ts) || !this.latestRobot ||
        this.nowMs() - raw.robot_state_ts > this.settings.maxRobotAgeMs ||
        raw.robot_state_ts < raw.observed_at_ms ||
        raw.robot_state_ts > this.latestRobot.receivedAtMs) return 'projection_pose_not_fresh';
    if (!Number.isFinite(this.stationarySinceMs) || raw.observed_at_ms < this.stationarySinceMs) {
      return 'projection_pose_not_fresh';
    }
    if ((raw.guard_blockers?.length || 0) || (raw.robot_pose_blockers?.length || 0)) {
      return raw.guard_blockers?.[0] || raw.robot_pose_blockers?.[0];
    }
    return null;
  }

  _expectedAnchorBase() {
    const anchor = this.supervisedAnchor;
    if (!anchor) return null;
    const attachment = anchor.attachment;
    if (!attachment) return [...anchor.base_xyz_m];
    if (!this.latestRobot ||
        angleDistance(this.latestRobot.euler, attachment.contact_tcp_euler_rad) >
          this.settings.orientationToleranceRad) return null;
    return anchor.base_xyz_m.map((value, index) => value + this.latestRobot.position[index] -
      attachment.contact_tcp_position_m[index]);
  }

  _frozenGuardPlan(observedAtMs, frameId) {
    const frozen = this.controller.state.plan || this.controller.latestTarget;
    return { ...frozen, observedAtMs, previewId: `projection:${this.supervisedAnchor.anchor_id}:${frameId}`,
      identityId: this.supervisedAnchor.target_id,
      calibrationId: this.supervisedAnchor.calibration_id,
      evidenceSource: 'rgb_fk_projection_guard' };
  }

  observerEnd(reason = 'observer_stream_eof') { this._invalidateTarget(reason); }

  _invalidateTarget(reason) {
    this.latestObservation = { valid: false, reason };
    this.latestProjectionGuard = null;
    this.nearfieldAuthorization = null;
    const phase = this.controller.snapshot().phase;
    if (!['idle', 'holding', 'aborted'].includes(phase)) {
      this.failurePhase = phase;
      this.controller.cancel(reason);
    }
    this._event('vision_invalid', { reason, controller_phase: this.controller.snapshot().phase });
  }

  _watchdog() {
    if (this.pending?.deadlineAtMs && this.nowMs() >= this.pending.deadlineAtMs) {
      const timedOut = this.pending;
      if (timedOut.kind === 'controller' && timedOut.command?.cmd === 'move_l') {
        this._event('motion_cancel_latched', {
          reason: 'robot_command_timeout',
          motion_stop_mode: 'after_current_bounded_segment',
          note: 'The SDK has no supported cancel-and-hold; no later segment will be sent.',
        });
      }
      this._robotFailure('robot_command_timeout', {
        phase: timedOut.phase || timedOut.kind,
        request_id: timedOut.command?.request_id,
        deadline_at_ms: timedOut.deadlineAtMs,
      });
      return;
    }
    const phase = this.snapshot().phase;
    if (!['idle', 'holding', 'aborted'].includes(phase) &&
        (!Number.isFinite(this.lastCameraCaptureMs) ||
         this.nowMs() - this.lastCameraCaptureMs > this.settings.maxCameraWatchdogAgeMs)) {
      this._invalidateTarget('observer_watchdog_stale');
    }
    this._writePoseSnapshot();
  }

  _preview(plan = this.controller.state?.plan) {
    const observation = this.latestObservation || {};
    return {
      target_ordinal: this.settings.targetOrdinal,
      target_id: this.lockedTargetId,
      frame_id: observation.frame_id,
      observed_at_ms: observation.observed_at_ms,
      pixel_uv: observation.pixel_uv,
      camera_xyz_m: observation.camera_xyz_m,
      base_xyz_m: observation.base_xyz_m,
      grasp_m: plan?.graspM,
      pregrasp_m: plan?.pregraspM,
      lift_m: plan?.retreatM,
      grasp_pose: plan?.graspM ? [...plan.graspM, ...this.settings.eulerRad] : undefined,
      pregrasp_pose: plan?.pregraspM ? [...plan.pregraspM, ...this.settings.eulerRad] : undefined,
      lift_pose: plan?.retreatM ? [...plan.retreatM, ...this.settings.eulerRad] : undefined,
      grasp_height_policy: plan?.graspHeightPolicy,
      fixed_grasp_base_z_m: plan?.fixedGraspBaseZM,
      surface_m: plan?.surfaceM || observation.base_surface_xyz_m,
      estimated_center_m: plan?.estimatedCenterM || observation.base_center_estimate_xyz_m ||
        observation.base_xyz_m,
      tcp_origin_m: this.latestRobot?.position,
      candidate_offset_base_m_applied: observation.candidate_offset_base_m_applied,
      calibration_id: observation.calibration_id,
      handeye_semantics: observation.handeye?.effective_matrix_semantics,
      calibration_physical_validation: observation.physical_validation,
    };
  }

  command(input) {
    const words = String(input).trim().split(/\s+/);
    const name = words[0].toLowerCase();
    if (!name) return { ok: false, reason: 'command_empty' };
    if (name === 'status') {
      this._event('status', { controller: this.snapshot(), connected: this.connected,
        moving: this.motionActive, contact: this.contact, preview: this._preview() });
      return { ok: true };
    }
    if (name === 'connect') {
      if (this.connected) return { ok: false, reason: 'already_connected' };
      if (this.connectRequested) return { ok: false, reason: 'connect_already_requested' };
      this.connectRequested = true;
      this.bridge.start();
      this.poseTimer = this.setTimer(() => this._watchdog(), 100);
      this.poseTimer?.unref?.();
      this._event('connect_requested', { behavior: 'power_on_hold_at_measured_joint_pose' });
      return { ok: true };
    }
    if (name === 'observe') return this._observe();
    if (name === 'stop') {
      this.controller.cancel('operator_emergency_stop');
      const sent = this.bridge.softwareStop();
      this._event('emergency_stop', { sent, depowers: true,
        note: 'software_stop calls SDK cleanup and disables the arm; it is not a hold command.' });
      return { ok: sent };
    }
    if (name === 'quit') {
      if (words[1] !== 'supported') return { ok: false, reason: 'use_quit_supported' };
      this.quitting = true;
      if (this.poseTimer) this.clearTimer(this.poseTimer);
      this.observerProcess?.kill('SIGTERM');
      this.bridge.shutdown();
      this._event('shutdown', { explicit: true });
      return { ok: true };
    }
    if (name === 'home') return this._home();
    if (name === 'open') return this._open(words[1] === 'supported');
    if (name === 'hover') return this._stage('hover');
    if (['descend', 'close', 'lift'].includes(name)) return this._stage(name);
    if (name === 'confirm') return this._confirm(words[1], words.slice(2).join('_'));
    if (name === 'new') return this._newTrial(words.slice(1));
    return { ok: false, reason: 'command_unknown' };
  }

  _observe() {
    if (!this.connected) return { ok: false, reason: 'robot_disconnected' };
    if (this.motionActive || this.pending) return { ok: false, reason: 'arm_motion_active' };
    const phase = this.snapshot().phase;
    if (!['idle', 'aborted'].includes(phase)) {
      return { ok: false, reason: `observer_restart_phase_not_safe:${phase}` };
    }
    if (this.holdingObjectPossible) return { ok: false, reason: 'holding_object_possible' };
    if (this.observerProcess) return { ok: false, reason: 'observer_already_running' };
    if (this.lockedTargetId) {
      return { ok: false, reason: 'target_identity_already_locked_start_new_session' };
    }
    return this._launchObserver('operator_observe');
  }

  _launchObserver(trigger) {
    if (this.observerProcess) return { ok: false, reason: 'observer_already_running' };
    if (typeof this.startObserver !== 'function') {
      return { ok: false, reason: 'observer_start_unavailable' };
    }
    try {
      const observerProcess = this.startObserver(this);
      if (!observerProcess) return { ok: false, reason: 'observer_start_failed' };
      this.observerProcess = observerProcess;
      this._event('observer_start_requested', { trigger, automatic_retry: false });
      return { ok: true };
    } catch (error) {
      this._event('observer_start_failed', { trigger, message: error.message });
      return { ok: false, reason: 'observer_start_failed' };
    }
  }

  _home() {
    if (this.snapshot().phase === 'holding') return { ok: false, reason: 'holding_object' };
    if (this.holdingObjectPossible) return { ok: false, reason: 'holding_object_possible' };
    const gate = this._continuationGate();
    if (!gate.approved) return { ok: false, reason: gate.reason };
    const current = this.latestRobot.joints;
    if (!finiteVector(current, 6)) return { ok: false, reason: 'joint_state_missing' };
    const target = radians(this.settings.homeJointsDeg);
    const duration = Math.ceil(10 * Math.max(2,
      2.1875 * Math.max(...target.map((v, i) => Math.abs(v - current[i]))) /
      this.settings.maxAngularSpeedRadS)) / 10;
    if (duration > 30) return { ok: false, reason: 'home_duration_exceeds_limit' };
    const command = { cmd: 'move_joint', joints_rad: target, time_sec: Number(duration.toFixed(9)),
      request_id: randomUUID(), source: 'preset:home' };
    this.pending = { kind: 'home', command };
    this._setCommandDeadline(this.pending, command);
    this._event('robot_command', { phase: 'home', command });
    if (!this.bridge.send(command)) {
      this._robotFailure('bridge_rejected', command);
      return { ok: false, reason: 'bridge_rejected' };
    }
    return { ok: true };
  }

  _open(supported = false) {
    if ((this.snapshot().phase === 'holding' || this.holdingObjectPossible) && !supported) {
      return { ok: false, reason: 'use_open_supported' };
    }
    const gate = this._continuationGate();
    if (!gate.approved) return { ok: false, reason: gate.reason };
    if (this.snapshot().phase === 'holding') {
      this.failurePhase = 'holding';
      this.controller.cancel('operator_supported_release');
    }
    const command = { cmd: 'gripper', position: 1, kp: 8, kd: 0.1,
      request_id: randomUUID(), source: 'grasp:supervised_open' };
    this.pending = { kind: 'open', command };
    this._setCommandDeadline(this.pending, command);
    this._event('robot_command', { phase: 'open', command });
    if (!this.bridge.send(command)) {
      this._robotFailure('bridge_rejected', command);
      return { ok: false, reason: 'bridge_rejected' };
    }
    return { ok: true };
  }

  _newTrial(words) {
    if (words[0] !== 'trial' || words.length > 2 ||
        (words.length === 2 && words[1] !== 'empty')) {
      return { ok: false, reason: 'use_new_trial_or_new_trial_empty' };
    }
    const explicitEmpty = words[1] === 'empty';
    if (!this.resultRecorded) return { ok: false, reason: 'current_trial_not_finished' };
    if (!this.connected) return { ok: false, reason: 'robot_disconnected' };
    if (this.motionActive || this.pending) return { ok: false, reason: 'arm_motion_active' };
    if (this.snapshot().phase === 'holding') return { ok: false, reason: 'holding_object' };
    if (this.holdingObjectPossible) return { ok: false, reason: 'holding_object_possible' };
    if (!this.latestRobot || this.nowMs() - this.latestRobot.receivedAtMs > this.settings.maxRobotAgeMs) {
      return { ok: false, reason: 'robot_state_stale' };
    }
    if (!Number.isFinite(this.stationarySinceMs)) {
      return { ok: false, reason: 'robot_not_stationary' };
    }
    if (!this.gripperOpen && !explicitEmpty) {
      return { ok: false, reason: 'new_trial_requires_verified_open_or_explicit_empty' };
    }
    const previousTrialId = this.trialId;
    const startedAtMs = this.nowMs();
    this.trialId = randomUUID();
    this.resultRecorded = false;
    this.failurePhase = null;
    this.contact = false;
    this.holdStartedAtMs = null;
    this.descendMeasuredZ = null;
    this.lastMotionCompletedAtMs = null;
    this.lastActionCompletedAtMs = null;
    this.lastStageFrameId = null;
    this.lastCameraCaptureMs = null;
    this.latestObservation = null;
    this.latestGuardFrame = null;
    this.latestProjectionGuard = null;
    this.nearfieldAuthorization = null;
    this.supervisedAnchor = null;
    this.homeAwaitingState = false;
    this.homeVerified = false;
    this.freshEvidenceAfterMs = startedAtMs;
    this.controller.latestTarget = null;
    this.controller.state = { phase: 'aborted', mode: null,
      reason: 'new_trial_requires_fresh_evidence', nextPhase: null, inFlight: null };
    this._event('new_trial_started', { previous_trial_id: previousTrialId,
      target_id_retained: this.lockedTargetId, operator_confirmed_empty: explicitEmpty,
      sdk_restarted: false, observer_restarted: false, automatic_motion: false });
    return { ok: true, trial_id: this.trialId };
  }

  _stage(phase) {
    if (this.resultRecorded) return { ok: false, reason: 'trial_result_already_recorded' };
    const state = this.snapshot();
    const expected = phase === 'hover' ? ['idle', 'aborted'] : ['preview_ready'];
    if (!expected.includes(state.phase) || (phase !== 'hover' && state.nextPhase !== phase)) {
      return { ok: false, reason: `stage_not_ready:${state.phase}:${state.nextPhase || 'none'}` };
    }
    if (phase === 'hover' && (!this.homeVerified || !this.gripperOpen)) {
      return { ok: false, reason: !this.homeVerified ? 'home_not_verified' : 'gripper_not_open' };
    }
    if (phase === 'close') this.descendMeasuredZ = this.latestRobot?.position[2];
    const useProjectionGuard = Boolean(this.supervisedAnchor &&
      ['descend', 'close', 'lift'].includes(phase));
    const stageEvidence = useProjectionGuard ? this.latestProjectionGuard : this.latestObservation;
    if ((useProjectionGuard ? stageEvidence?.projection_guard_valid !== true : !stageEvidence?.valid) ||
        stageEvidence?.frame_id === this.lastStageFrameId) {
      return { ok: false, reason: 'fresh_stage_observation_required' };
    }
    if (phase !== 'hover' && Number.isFinite(this.lastActionCompletedAtMs) &&
        (stageEvidence.observed_at_ms < this.lastActionCompletedAtMs ||
         stageEvidence.robot_state_ts < this.lastActionCompletedAtMs ||
         this.latestRobot.receivedAtMs < this.lastActionCompletedAtMs)) {
      return { ok: false, reason: 'post_motion_observation_required' };
    }
    const checked = this._authorizeObservation();
    if (!checked.approved) return { ok: false, reason: checked.reason };
    if (phase === 'hover' && this.settings.observationHeightBaseM !== undefined &&
        !this.supervisedAnchor) {
      const anchor = this._approveNearfieldAnchor(checked.plan);
      if (!anchor.approved) {
        this.failurePhase = 'hover';
        this.controller.cancel(anchor.reason);
        return { ok: false, reason: anchor.reason };
      }
    }
    const approvedPlan = this.supervisedAnchor ? this.nearfieldAuthorization.plan : checked.plan;
    this._event('stage_preview', { requested_phase: phase, operator_confirmation: true,
      ...this._preview(approvedPlan) });
    this.lastStageFrameId = stageEvidence.frame_id;
    const result = phase === 'hover' ? this.controller.start('step') : this.controller.advance();
    if (!result.ok) return result;
    if (phase === 'hover' && this.nearfieldAuthorization?.initialAnchor === true) {
      this.nearfieldAuthorization = null;
    }
    return { ok: true, phase };
  }

  _approveNearfieldAnchor(frozenPlan) {
    const observation = this.latestObservation;
    const reference = observation?.nearfield_reference_candidate;
    const calibrationId = observation?.calibration_id;
    const valid = reference && reference.valid === true &&
      reference.target_id === observation.target_id &&
      reference.calibration_id === calibrationId && reference.frame_id === observation.frame_id &&
      reference.observed_at_ms === observation.observed_at_ms &&
      reference.observation_height_base_m === this.settings.observationHeightBaseM &&
      reference.bottle_diameter_m === this.settings.bottleDiameterM &&
      finiteVector(reference.base_xyz_m) && finiteVector(reference.source_camera_xyz_m) &&
      finiteVector(reference.source_pixel_uv, 2);
    if (!valid) return { approved: false, reason: 'nearfield_reference_invalid' };
    const xyDiscrepancy = Math.hypot(reference.base_xyz_m[0] - frozenPlan.graspM[0],
      reference.base_xyz_m[1] - frozenPlan.graspM[1]);
    if (xyDiscrepancy > MAX_REFERENCE_PLAN_XY_DRIFT_M) {
      return { approved: false, reason: 'nearfield_reference_plan_mismatch' };
    }
    this.supervisedAnchor = {
      anchor_id: randomUUID(), trial_id: this.trialId, target_id: observation.target_id,
      calibration_id: calibrationId, approved_at_ms: this.nowMs(),
      base_xyz_m: [...reference.base_xyz_m], reference: JSON.parse(JSON.stringify(reference)),
    };
    this.nearfieldAuthorization = { approved: true, initialAnchor: true,
      plan: { ...frozenPlan, evidenceSource: 'approved_rgbd_nearfield_anchor' } };
    this.controller.latestTarget = this.nearfieldAuthorization.plan;
    this._event('nearfield_anchor_approved', { anchor_id: this.supervisedAnchor.anchor_id,
      source_frame_id: reference.frame_id,
      plan_reference_xy_discrepancy_m: Number(xyDiscrepancy.toFixed(9)),
      frozen_grasp_m: [...frozenPlan.graspM], anchor_base_xyz_m: [...reference.base_xyz_m] });
    this._writePoseSnapshot();
    return { approved: true };
  }

  _sendControllerCommand(original, phase) {
    try {
      const segments = original.cmd === 'move_l'
        ? this._motionSegments(phase, original.position_m)
        : [{ position: null, euler: null, leg: 'gripper' }];
      this.pending = { kind: 'controller', phase, controllerCommand: original,
        segments, index: 0, cancelAfterCurrent: false, awaitingGuard: false };
      this._sendPendingSegment();
      return true;
    } catch (error) {
      this._event('command_rejected', { phase, reason: error.message });
      this.pending = null;
      return false;
    }
  }

  _motionSegments(phase, target) {
    if (!this.latestRobot) throw new Error('robot_state_missing');
    const currentPosition = this.latestRobot.position;
    const currentEuler = this.latestRobot.euler;
    const legs = [];
    if (phase === 'hover') {
      const safeZ = Math.max(this.settings.safeTransitZM, target[2]);
      legs.push({ name: 'vertical_to_safe', target: [currentPosition[0], currentPosition[1], safeZ],
        euler: currentEuler, maxStep: 0.02 });
      legs.push({ name: 'overhead_translate', target: [target[0], target[1], safeZ],
        euler: this.settings.eulerRad, maxStep: 0.02 });
      legs.push({ name: 'vertical_to_pregrasp', target: [...target],
        euler: this.settings.eulerRad, maxStep: 0.02 });
    } else {
      legs.push({ name: phase, target: [...target], euler: this.settings.eulerRad, maxStep: 0.01 });
    }
    const segments = [];
    let from = [...currentPosition];
    let fromEuler = [...currentEuler];
    for (const leg of legs) {
      const count = Math.max(1, Math.ceil(distance(from, leg.target) / leg.maxStep));
      for (let step = 1; step <= count; step += 1) {
        const fraction = step / count;
        const position = from.map((value, index) => value + fraction * (leg.target[index] - value));
        const euler = fromEuler.map((value, index) => value + fraction *
          Math.atan2(Math.sin(leg.euler[index] - value), Math.cos(leg.euler[index] - value)));
        segments.push({ position, euler, leg: leg.name });
      }
      from = [...leg.target];
      fromEuler = [...leg.euler];
    }
    return segments;
  }

  _sendPendingSegment() {
    const pending = this.pending;
    if (!pending || pending.cancelAfterCurrent || this.snapshot().phase === 'aborted') return;
    if (pending.phase === 'close') {
      const command = { cmd: 'gripper', position: 0, kp: 2, kd: 0.1,
        request_id: randomUUID(), source: 'grasp:supervised_close' };
      this.gripperOpen = false;
      this.holdingObjectPossible = true;
      pending.command = command;
      this._setCommandDeadline(pending, command);
      this._event('robot_command', { phase: pending.phase, segment: 1, segments: 1, command });
      if (!this.bridge.send(command)) this._robotFailure('bridge_rejected', command);
      return;
    }
    const segment = pending.segments[pending.index];
    const origin = pending.index === 0 ? this.latestRobot.position : pending.segments[pending.index - 1].position;
    const originEuler = pending.index === 0 ? this.latestRobot.euler : pending.segments[pending.index - 1].euler;
    const translationSeconds = motionDuration(origin, segment.position, this.settings.maxSpeedMps);
    const angularSeconds = Math.max(2, 2.1875 * angleDistance(originEuler, segment.euler) /
      this.settings.maxAngularSpeedRadS);
    const seconds = Math.ceil(10 * Math.max(translationSeconds, angularSeconds)) / 10;
    if (seconds > 30) throw new Error('segment_duration_exceeds_limit');
    const command = { cmd: 'move_l', position: [...segment.position], euler: [...segment.euler],
      time_sec: Number(seconds.toFixed(9)), request_id: randomUUID(),
      source: `grasp:supervised_${pending.phase}` };
    pending.command = command;
    this._setCommandDeadline(pending, command);
    pending.segmentStartFrameId = this.latestGuardFrame?.frame_id ?? this.latestObservation?.frame_id;
    pending.segmentStartedAtMs = this.nowMs();
    if (!this._insideWorkspace(origin) || !this._insideWorkspace(segment.position)) {
      return this._robotFailure('segment_workspace_rejected', { origin, target: segment.position });
    }
    this._event('robot_command', { phase: pending.phase, leg: segment.leg,
      segment: pending.index + 1, segments: pending.segments.length,
      origin_position_m: [...origin], requested_speed_mps: this.settings.maxSpeedMps,
      reference_duration_s: command.time_sec, command });
    if (!this.bridge.send(command)) this._robotFailure('bridge_rejected', command);
  }

  _commandComplete(event) {
    const pending = this.pending;
    if (!pending?.command || event.request_id !== pending.command.request_id ||
        event.command !== pending.command.cmd) return;
    if (pending.kind === 'home') {
      pending.deadlineAtMs = this.nowMs() + this.settings.commandTimeoutGraceMs;
      this.homeAwaitingState = true;
      this.bridge.send({ cmd: 'get_state' });
      return;
    }
    if (pending.kind === 'open') {
      if (event.reached !== true) return this._robotFailure('gripper_open_not_reached', event);
      this._event('command_verified', { phase: 'open', actual_position: event.actual_position });
      this.gripperOpen = true;
      this.holdingObjectPossible = false;
      this.pending = null;
      return;
    }
    if (pending.cancelAfterCurrent || this.snapshot().phase === 'aborted') {
      this._event('bounded_segment_stopped', { phase: pending.phase,
        completed_request_id: event.request_id, further_segments_sent: false });
      this.pending = null;
      return;
    }
    if (pending.phase === 'close') {
      const actual = Number(event.actual_position);
      this.contact = event.reached === false && event.moved === true &&
        Number.isFinite(actual) && actual >= 0.08 && actual <= 0.95;
      if (!this.contact) return this._robotFailure('object_contact_not_detected', event);
      this._event('command_verified', { phase: 'close', contact: true, actual_position: actual });
      this.gripperOpen = false;
      this.lastActionCompletedAtMs = this.nowMs();
      this.lastStageFrameId = this.latestObservation?.frame_id;
      if (this.supervisedAnchor) {
        this.supervisedAnchor.attachment = {
          contact_tcp_position_m: [...this.latestRobot.position],
          contact_tcp_euler_rad: [...this.latestRobot.euler],
          contact_verified_at_ms: this.lastActionCompletedAtMs,
        };
        this._writePoseSnapshot();
      }
      this.pending = null;
      this.controller.complete('gripper');
      return;
    }
    if (event.reached !== true || !Number.isFinite(event.position_error_m) ||
        event.position_error_m > this.settings.positionToleranceM ||
        !Number.isFinite(event.orientation_error_rad) ||
        event.orientation_error_rad > this.settings.orientationToleranceRad) {
      return this._robotFailure('cartesian_endpoint_not_verified', event);
    }
    this._event('segment_verified', { phase: pending.phase, leg: pending.segments[pending.index].leg,
      request_id: event.request_id, position_error_m: event.position_error_m,
      orientation_error_rad: event.orientation_error_rad });
    pending.index += 1;
    if (pending.index < pending.segments.length) {
      pending.awaitingGuard = true;
      pending.deadlineAtMs = null;
      pending.segmentCompletedAtMs = this.nowMs();
      this._event('segment_guard_wait', { phase: pending.phase,
        completed_segment: pending.index, required: 'new_fresh_locked_camera_frame' });
      return this._resumeAfterSegmentGuard();
    }
    const original = pending.controllerCommand;
    const phase = pending.phase;
    this.lastMotionCompletedAtMs = this.nowMs();
    this.lastActionCompletedAtMs = this.lastMotionCompletedAtMs;
    this.lastStageFrameId = this.latestObservation?.frame_id;
    this.pending = null;
    this.controller.complete('move_l', original.request_id);
    if (phase === 'lift') this.holdStartedAtMs = this.nowMs();
  }

  _resumeAfterSegmentGuard() {
    const pending = this.pending;
    if (!pending || pending.kind !== 'controller' || !pending.awaitingGuard ||
        pending.cancelAfterCurrent || this.motionActive || this.snapshot().phase === 'aborted') return false;
    const raw = this.latestGuardFrame;
    if (this.supervisedAnchor && ['hover', 'descend', 'lift'].includes(pending.phase)) {
      const fresh = Number.isFinite(raw?.observed_at_ms) && raw.observed_at_ms <= this.nowMs() &&
        this.nowMs() - raw.observed_at_ms <= this.settings.maxObservationAgeMs;
      const changed = raw?.frame_id !== undefined && raw.frame_id !== pending.segmentStartFrameId;
      const robotFresh = this.latestRobot &&
        this.nowMs() - this.latestRobot.receivedAtMs <= this.settings.maxRobotAgeMs &&
        this.latestRobot.receivedAtMs >= pending.segmentCompletedAtMs &&
        Number.isFinite(raw?.robot_state_ts) && raw.robot_state_ts <= this.latestRobot.receivedAtMs &&
        raw.robot_state_ts >= raw.observed_at_ms &&
        this.nowMs() - raw.robot_state_ts <= this.settings.maxRobotAgeMs;
      const guardValid = this.latestProjectionGuard === raw && raw?.projection_guard_valid === true &&
        raw?.rgb_observation_valid === true && raw?.trial_id === this.trialId &&
        raw?.anchor_id === this.supervisedAnchor.anchor_id &&
        raw?.target_id === this.supervisedAnchor.target_id &&
        raw?.calibration_id === this.supervisedAnchor.calibration_id &&
        (!Array.isArray(raw?.guard_blockers) || raw.guard_blockers.length === 0) &&
        (!Array.isArray(raw?.robot_pose_blockers) || raw.robot_pose_blockers.length === 0);
      if (!fresh || !changed || !robotFresh || !guardValid ||
          raw.observed_at_ms < pending.segmentCompletedAtMs) return false;
      pending.awaitingGuard = false;
      this._event('segment_guard_passed', { phase: pending.phase, frame_id: raw.frame_id,
        observed_at_ms: raw.observed_at_ms, target_id: raw.target_id,
        evidence_source: 'rgb_fk_projection_guard' });
      this._sendPendingSegment();
      return true;
    }
    const calibrationId = raw?.handeye?.calibration_id || raw?.calibration_id;
    const fresh = Number.isFinite(raw?.observed_at_ms) && raw.observed_at_ms <= this.nowMs() &&
      this.nowMs() - raw.observed_at_ms <= this.settings.maxObservationAgeMs;
    const changed = raw?.frame_id !== undefined && raw.frame_id !== pending.segmentStartFrameId;
    const cameraValid = this.latestObservation?.valid === true &&
      raw?.event === 'bottle_observation' && raw.camera_observation_valid === true &&
      raw.track_state === 'locked' && raw.target_id === this.lockedTargetId &&
      finiteVector(raw.camera_xyz_m) && finiteVector(raw.pixel_uv, 2);
    const calibrationValid = calibrationId && calibrationId === this.controller.state.calibrationId;
    const robotFresh = this.latestRobot &&
      this.nowMs() - this.latestRobot.receivedAtMs <= this.settings.maxRobotAgeMs &&
      this.latestRobot.receivedAtMs >= pending.segmentCompletedAtMs;
    if (!fresh || !changed || !cameraValid || !calibrationValid || !robotFresh) return false;
    pending.awaitingGuard = false;
    this._event('segment_guard_passed', { phase: pending.phase, frame_id: raw.frame_id,
      observed_at_ms: raw.observed_at_ms, target_id: raw.target_id });
    this._sendPendingSegment();
    return true;
  }

  _verifyHomeState() {
    if (!this.homeAwaitingState || !this.pending || this.pending.kind !== 'home') return;
    this.homeAwaitingState = false;
    const target = radians(this.settings.homeJointsDeg);
    const tolerance = (this.settings.homeJointToleranceDeg ?? 1.0) * Math.PI / 180;
    const error = this.latestRobot.joints && Math.max(...target.map((v, i) => Math.abs(v - this.latestRobot.joints[i])));
    if (!Number.isFinite(error) || error > tolerance) return this._robotFailure('home_joint_error', { error });
    if (distance(this.latestRobot.position, this.settings.homeTcpM) > this.settings.positionToleranceM) {
      return this._robotFailure('home_tcp_error', { actual: this.latestRobot.position });
    }
    this._event('command_verified', { phase: 'home', max_joint_error_rad: error,
      tcp_error_m: distance(this.latestRobot.position, this.settings.homeTcpM) });
    this.homeVerified = true;
    this.lastActionCompletedAtMs = this.nowMs();
    this.pending = null;
  }

  _robotFailure(reason, detail) {
    this._event('robot_command_failed', { reason, detail });
    this.failurePhase = this.pending?.phase || this.pending?.kind || this.snapshot().phase;
    this.pending = null;
    this.controller.fail(reason);
    this._recordFailure(reason);
  }

  _insideWorkspace(point) {
    return point.every((value, index) => {
      const axis = ['x', 'y', 'z'][index];
      const bounds = this.settings.workspace[axis];
      return Number.isFinite(value) && value >= bounds[0] && value <= bounds[1];
    });
  }

  _setCommandDeadline(pending, command) {
    const timeoutMs = command.cmd === 'gripper'
      ? this.settings.gripperCommandTimeoutMs
      : Number(command.time_sec) * 1000 + this.settings.commandTimeoutGraceMs;
    pending.deadlineAtMs = this.nowMs() + timeoutMs;
    pending.commandStartedAtMs = this.nowMs();
    this._event('command_deadline', { phase: pending.phase || pending.kind,
      request_id: command.request_id, deadline_at_ms: pending.deadlineAtMs,
      timeout_ms: timeoutMs });
  }

  _recordFailure(reason) {
    if (this.resultRecorded) return;
    const phase = this.failurePhase || this.snapshot().phase;
    const result = { ts: this.nowMs(), schema: 'thirdhand-supervised-grasp-result-v1',
      trial_id: this.trialId, target_id: this.lockedTargetId, success: false,
      failure_phase: phase, failure_category: failureCategory(reason, phase), reason,
      contact: this.contact, calibration_id: this.latestObservation?.calibration_id,
      physical_calibration: this.latestObservation?.physical_validation || 'pending' };
    this.resultRecorded = true;
    this.writeResult(result);
    this._event('trial_result', result);
  }

  _confirm(value, explicitFailureCategory = '') {
    if (!['success', 'failure'].includes(value)) return { ok: false, reason: 'confirm_success_or_failure' };
    if (this.snapshot().phase !== 'holding' || !Number.isFinite(this.holdStartedAtMs)) {
      return { ok: false, reason: 'not_holding' };
    }
    if (this.resultRecorded) return { ok: false, reason: 'trial_result_already_recorded' };
    if (value === 'failure') {
      const category = normalizeFailureCategory(explicitFailureCategory);
      if (!category) return { ok: false, reason: 'confirm_failure_requires_category' };
      const result = { ts: this.nowMs(), schema: 'thirdhand-supervised-grasp-result-v1',
        trial_id: this.trialId, target_id: this.lockedTargetId, success: false,
        failure_phase: 'holding', failure_category: category,
        reason: `operator_reported_${category}`, failure_source: 'operator_confirmation',
        contact: this.contact, calibration_id: this.latestObservation?.calibration_id,
        physical_calibration: this.latestObservation?.physical_validation || 'pending' };
      this.writeResult(result);
      this.resultRecorded = true;
      this._event('trial_result', result);
      return { ok: true, success: false };
    }
    if (!this.latestRobot || this.nowMs() - this.latestRobot.receivedAtMs > this.settings.maxRobotAgeMs) {
      return { ok: false, reason: 'robot_state_stale' };
    }
    const check = verifyHold({ startZ: this.descendMeasuredZ,
      currentZ: this.latestRobot?.position[2], elapsedMs: this.nowMs() - this.holdStartedAtMs,
      contact: this.contact, visualConfirmed: value === 'success' });
    const visual = true;
    const success = check.passed && visual;
    const result = { ts: this.nowMs(), schema: 'thirdhand-supervised-grasp-result-v1',
      trial_id: this.trialId, target_id: this.lockedTargetId,
      success,
      ...(success ? {} : { failure_phase: 'holding', failure_category: 'grasp',
        reason: 'hold_telemetry_criteria_not_met', failure_source: 'hold_telemetry' }),
      measured_hold: check,
      visual_confirmation: { bottle_bottom_lifted_5cm_for_3s: visual,
        operator_command: `confirm ${value}` },
      contact: this.contact,
      calibration_id: this.latestObservation?.calibration_id,
      physical_calibration: this.latestObservation?.physical_validation || 'pending' };
    this.writeResult(result);
    this.resultRecorded = true;
    this._event('trial_result', result);
    return result.success ? { ok: true } : { ok: false, reason: 'trial_not_successful' };
  }
}

function atomicJsonWriter(filename) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  return payload => {
    const temporary = `${filename}.${process.pid}.tmp`;
    fs.writeFileSync(temporary, `${JSON.stringify(payload)}\n`, 'utf8');
    fs.renameSync(temporary, filename);
  };
}

function appendJsonl(filename) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  return payload => fs.appendFileSync(filename, `${JSON.stringify(payload)}\n`, 'utf8');
}

function resolveArtifactPaths(settings, mode) {
  const suffix = filename => {
    const resolved = path.resolve(filename);
    if (mode !== 'simulate') return resolved;
    const extension = path.extname(resolved);
    const stem = extension ? resolved.slice(0, -extension.length) : resolved;
    return `${stem}.simulate${extension}`;
  };
  return {
    poseFile: suffix(settings.robotPoseFile || '/tmp/thirdhand-supervised-grasp-robot-pose.json'),
    auditFile: suffix(settings.auditJsonl || 'artifacts/vision/supervised-grasp/cli-events.jsonl'),
    resultFile: suffix(settings.resultsJsonl || 'artifacts/vision/supervised-grasp/results.jsonl'),
  };
}

function createLiveBridge(root) {
  const { StartouchBridge } = require(path.join(root, 'web-control/server/startouch-bridge.js'));
  const config = require(path.join(root, 'web-control/server/config.js'));
  return new StartouchBridge({ ...config.robot, simulate: false, dryRun: false });
}

function buildObserverArgs(cli, { visionRoot, poseFile, visionConfig, handeyeFile }) {
  const script = path.join(visionRoot, 'scripts/vision/observe_grasp_bottle.py');
  const args = [script, '--ordinal', String(cli.settings.targetOrdinal), '--allow-camera',
    '--watch-jsonl', '--robot-pose-file', poseFile, '--handeye-parent-frame', 'sdk_tool'];
  if (visionConfig || cli.settings.visionConfig) args.push('--config', visionConfig || cli.settings.visionConfig);
  if (handeyeFile || cli.settings.handeyeFile) args.push('--handeye', handeyeFile || cli.settings.handeyeFile);
  if (cli.settings.graspHeightBaseM !== undefined) {
    args.push('--grasp-height-base-m', String(cli.settings.graspHeightBaseM));
  }
  if (cli.settings.observationHeightBaseM !== undefined) {
    args.push('--observation-height-base-m', String(cli.settings.observationHeightBaseM));
  }
  if (cli.settings.bottleDiameterM !== undefined) {
    args.push('--bottle-diameter-m', String(cli.settings.bottleDiameterM));
  }
  if (cli.settings.observerOverlayFile !== undefined) {
    args.push('--output-overlay', cli.settings.observerOverlayFile);
  }
  return args;
}

function startObserver(cli, options, poseFile) {
  const args = buildObserverArgs(cli, { visionRoot: options.visionRoot, poseFile });
  const child = spawn(options.visionPython, args, {
    cwd: options.visionRoot,
    env: { ...process.env, PYTHONPATH: path.join(options.visionRoot, 'src') },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  readline.createInterface({ input: child.stdout }).on('line', line => cli.observerLine(line));
  readline.createInterface({ input: child.stderr }).on('line', line =>
    cli._event('observer_log', { message: line }));
  let ended = false;
  const finish = reason => {
    if (ended) return;
    ended = true;
    if (cli.observerProcess === child) cli.observerProcess = null;
    if (!cli.quitting) cli.observerEnd(reason);
  };
  child.on('error', error => finish(`observer_start_failed:${error.message}`));
  child.on('exit', (code, signal) => {
    finish(`observer_stream_eof:${signal || code}`);
  });
  cli._event('observer_started', { executable: options.visionPython, args,
    read_only_camera: true, robot_control_enabled: false });
  return child;
}

function main(argv = process.argv.slice(2)) {
  let options;
  try { options = parseArgs(argv); } catch (error) {
    console.error(error.message);
    console.error(HELP);
    return 2;
  }
  if (options.mode === 'help') {
    console.log(HELP);
    return 0;
  }
  const settings = validateSettings(options.settings);
  const { poseFile, auditFile, resultFile } = resolveArtifactPaths(settings, options.mode);
  const eventWriter = appendJsonl(auditFile);
  const executionMode = options.mode;
  const cli = new SupervisedGraspCli({
    bridge: options.mode === 'simulate' ? new OfflineBridge(settings) : createLiveBridge(options.bridgeRoot),
    settings,
    writeEvent(event) {
      const marked = { ...event, execution_mode: executionMode };
      console.log(JSON.stringify(marked));
      eventWriter(marked);
    },
    writeResult(result) { appendJsonl(resultFile)({ ...result, execution_mode: executionMode }); },
    writePose: atomicJsonWriter(poseFile),
    startObserver: options.mode === 'live'
      ? owner => startObserver(owner, options, poseFile)
      : null,
  });
  if (options.mode === 'live') {
    let observerStarted = false;
    cli.bridge.on('robot_state', () => {
      if (!observerStarted) {
        observerStarted = true;
        cli._launchObserver('initial_robot_state');
      }
    });
  } else if (settings.simulatedObservation) {
    cli.bridge.on('robot_state', () => setImmediate(() =>
      cli.observerLine(JSON.stringify(settings.simulatedObservation))));
  }
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout,
    terminal: process.stdin.isTTY });
  terminal.on('line', line => {
    const result = cli.command(line);
    console.log(JSON.stringify({ type: 'operator_command_result', command: line.trim(), ...result }));
    if (line.trim() === 'quit supported' && result.ok) terminal.close();
  });
  console.log(HELP);
  return 0;
}

if (require.main === module) process.exitCode = main();

module.exports = { HELP, OfflineBridge, SupervisedGraspCli, main,
  buildObserverArgs, failureCategory, normalizeObservation, parseArgs, resolveArtifactPaths,
  startObserver, validateSettings };
