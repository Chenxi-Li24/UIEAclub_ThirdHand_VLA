'use strict';

const { randomUUID } = require('crypto');
const { BaseFrameTargetLock, distance } = require('../observation/base_target_lock');
const { DEFAULT_WORKSPACE, checkWorkspace } = require('../safety/workspace_check');

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function clampVector(vector, maxNorm) {
  const norm = Math.hypot(...vector);
  if (norm <= maxNorm) return [...vector];
  return vector.map(value => value * maxNorm / norm);
}

function previewOf(target) {
  return target?.preview ?? target?.graspPreview ?? null;
}

class VisualAlignController {
  constructor({
    executionEnabled,
    getRobotState,
    selectBottle,
    resetTargetPoseReference,
    sendRobot,
    startGrasp,
    onStatus = () => {},
    nowMs = Date.now,
    idFactory = randomUUID,
    targetLock = null,
    stableWindow = 3,
    graspOffsetBaseM = [0, 0, 0],
    horizontalEulerRad = [0, 0, 0],
    alignStandoffM = 0.10,
    safeTransitZM = null,
    maxCoarseTranslationM = 0.40,
    maxRefineStepM = 0.005,
    alignmentToleranceM = 0.006,
    maxRefineSteps = 20,
    workspace = DEFAULT_WORKSPACE,
    linearSpeedMps = 0.03,
  }) {
    if (typeof getRobotState !== 'function' || typeof selectBottle !== 'function' ||
        typeof resetTargetPoseReference !== 'function' ||
        typeof sendRobot !== 'function' || typeof startGrasp !== 'function' ||
        typeof onStatus !== 'function' || !vector3(graspOffsetBaseM) ||
        !vector3(horizontalEulerRad) || !Number.isFinite(maxRefineStepM) ||
        maxRefineStepM <= 0 || maxRefineStepM > 0.005 ||
        !(safeTransitZM === null || (Number.isFinite(safeTransitZM) &&
          safeTransitZM > 0)) ||
        !Number.isFinite(linearSpeedMps) || linearSpeedMps <= 0 ||
        linearSpeedMps > 0.10 ||
        checkWorkspace([0, 0, 0], workspace, 'alignment').blockers.includes(
          'alignment_config_invalid'
        )) {
      throw new TypeError('visual align controller dependencies are invalid');
    }
    this.executionEnabled = executionEnabled === true;
    this.getRobotState = getRobotState;
    this.selectBottle = selectBottle;
    this.resetTargetPoseReference = resetTargetPoseReference;
    this.sendRobot = sendRobot;
    this.startGrasp = startGrasp;
    this.onStatus = onStatus;
    this.nowMs = nowMs;
    this.idFactory = idFactory;
    this.targetLock = targetLock || new BaseFrameTargetLock({
      stableWindow,
      requiredStableSamples: stableWindow,
    });
    this.graspOffsetBaseM = [...graspOffsetBaseM];
    this.horizontalEulerRad = [...horizontalEulerRad];
    this.alignStandoffM = alignStandoffM;
    this.safeTransitZM = safeTransitZM;
    this.maxCoarseTranslationM = maxCoarseTranslationM;
    this.maxRefineStepM = maxRefineStepM;
    this.alignmentToleranceM = alignmentToleranceM;
    this.maxRefineSteps = maxRefineSteps;
    this.workspace = Object.freeze({
      x: Object.freeze([...workspace.x]),
      y: Object.freeze([...workspace.y]),
      z: Object.freeze([...workspace.z]),
    });
    this.linearSpeedMps = linearSpeedMps;
    if (this.safeTransitZM !== null && (
      this.safeTransitZM < this.workspace.z[0] ||
      this.safeTransitZM > this.workspace.z[1]
    )) throw new TypeError('safe transit height is outside workspace');
    this.session = null;
    this.inFlight = null;
  }

  get active() {
    return this.session !== null && ![
      'complete', 'aborted', 'handed_off',
    ].includes(this.session.phase);
  }

  snapshot() {
    if (!this.session) return { active: false, phase: 'idle' };
    return {
      active: this.active,
      sessionId: this.session.sessionId,
      requestId: this.session.requestId,
      phase: this.session.phase,
      targetId: this.session.targetId,
      stableId: this.session.targetId,
      motionEpoch: this.session.motionEpoch,
      alignmentStage: this.session.alignmentStage,
      calibrationId: this.targetLock.snapshot().calibrationId,
      refineSteps: this.session.refineSteps,
      reason: this.session.reason,
      lock: this.targetLock.snapshot(),
    };
  }

  start({ targetId, requestId } = {}) {
    if (this.executionEnabled !== true) {
      return { accepted: false, reason: 'visual_align_disabled' };
    }
    if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5) {
      return { accepted: false, reason: 'target_id_invalid' };
    }
    if (typeof requestId !== 'string' || !requestId) {
      return { accepted: false, reason: 'request_id_invalid' };
    }
    if (this.active) return { accepted: false, reason: 'visual_align_active' };
    const gate = this._robotGate();
    if (gate !== null) return { accepted: false, reason: gate };
    const sessionId = this.idFactory();
    if (!UUID_PATTERN.test(sessionId)) return { accepted: false, reason: 'session_id_invalid' };
    this.targetLock.begin({ stableId: targetId, requestId, motionEpoch: 0 });
    this.inFlight = null;
    this.session = {
      sessionId,
      requestId,
      targetId,
      phase: 'acquiring',
      motionEpoch: 0,
      refineSteps: 0,
      alignmentStage: this.safeTransitZM === null ? 'pregrasp' : 'safe_height',
      reason: null,
    };
    if (this.selectBottle({
      type: 'select_bottle', stable_id: targetId, request_id: requestId,
    }) !== true) return this._abort('vision_transport_unavailable');
    this._publish();
    return { accepted: true, sessionId, requestId, phase: 'acquiring' };
  }

  onVisionTargets(targets) {
    if (!this.active || this.inFlight !== null) {
      return { handled: false, reason: 'vision_not_expected' };
    }
    if (!['acquiring', 'settling', 'reobserving'].includes(this.session.phase)) {
      return { handled: false, reason: 'vision_phase_ignored' };
    }
    const gate = this._robotGate();
    if (gate !== null) return { handled: false, reason: gate };
    if (this.session.phase === 'settling') {
      this.session.phase = 'reobserving';
      this._publish();
    }
    const observed = this.targetLock.observe(targets, this.nowMs());
    if (observed.accepted !== true) {
      const reason = observed.reason === 'base_stability_hits_insufficient'
        ? 'fresh_depth_required' : observed.reason;
      this.session.reason = reason;
      this._publish();
      return { handled: true, accepted: false, reason };
    }
    this.session.reason = null;
    if (this.session.phase === 'acquiring') {
      return this.safeTransitZM === null
        ? this._sendPregrasp(observed.pointM)
        : this._sendSafeHeight();
    }
    if (this.session.alignmentStage === 'over_pregrasp') {
      return this._sendOverPregrasp(observed.pointM);
    }
    if (this.session.alignmentStage === 'pregrasp') {
      return this._sendPregrasp(observed.pointM);
    }
    return this._refineOrHandoff(observed);
  }

  onRobotEvent(event) {
    if (!this.active) return { handled: false, reason: 'visual_align_inactive' };
    if (event?.type === 'connection' && event.connected === false) {
      return this._abort('robot_disconnected');
    }
    if (event?.type === 'software_stop') return this._abort('software_stop');
    if (!this.inFlight || !['command_complete', 'error'].includes(event?.type)) {
      return { handled: false, reason: 'event_ignored' };
    }
    if (event.request_id !== this.inFlight.requestId) {
      return { handled: false, reason: 'request_mismatch' };
    }
    if (event.type === 'error' || event.reached !== true) {
      return this._abort('visual_align_move_failed');
    }
    const completedPhase = this.inFlight.phase;
    this.inFlight = null;
    if (completedPhase === 'moving_to_safe_height') {
      this.session.alignmentStage = 'over_pregrasp';
    } else if (completedPhase === 'moving_over_pregrasp') {
      this.session.alignmentStage = 'pregrasp';
    } else {
      this.session.alignmentStage = 'refine';
    }
    this.session.motionEpoch += 1;
    this.targetLock.resetEvidence(this.session.motionEpoch);
    if (this.resetTargetPoseReference({
      type: 'reset_target_pose_reference',
      request_id: this.session.requestId,
      motion_epoch: this.session.motionEpoch,
    }) !== true) return this._abort('vision_pose_reset_unavailable');
    this.session.phase = 'settling';
    this._publish();
    return { handled: true, phase: 'settling', motionEpoch: this.session.motionEpoch };
  }

  cancel(reason = 'operator_cancelled') {
    if (!this.active) return { accepted: false, reason: 'visual_align_inactive' };
    return this._abort(reason);
  }

  _robotGate() {
    const robot = this.getRobotState();
    if (!robot || robot.connected !== true) return 'robot_not_connected';
    if (robot.healthy !== true) return 'robot_not_healthy';
    if (robot.poseFrame !== 'robot_flange') return 'robot_pose_frame_invalid';
    if (!Number.isFinite(robot.gripperWidthM) || robot.gripperWidthM < 0 ||
        robot.gripperWidthM > 0.080) return 'gripper_not_ready';
    if (robot.moving === true) return 'arm_motion_active';
    if (robot.stateFresh !== true || robot.stationary !== true ||
        !vector3(robot.flangePositionM)) return 'robot_state_not_stationary';
    return null;
  }

  _corrected(pointM) {
    return pointM.map((value, index) => Number(
      (value + this.graspOffsetBaseM[index]).toFixed(12)
    ));
  }

  _pregrasp(pointM) {
    const corrected = this._corrected(pointM);
    return [
      Number((corrected[0] - this.alignStandoffM).toFixed(12)),
      corrected[1], corrected[2],
    ];
  }

  _withinWorkspace(pointM) {
    return checkWorkspace(pointM, this.workspace, 'alignment').allowed;
  }

  _sendPregrasp(pointM) {
    const robot = this.getRobotState();
    const position = this._pregrasp(pointM);
    if (!this._withinWorkspace(position) ||
        distance(position, robot.flangePositionM) > this.maxCoarseTranslationM) {
      return this._abort('pregrasp_out_of_workspace');
    }
    return this._sendMove('moving_to_pregrasp', position);
  }

  _sendSafeHeight() {
    const robot = this.getRobotState();
    const position = [
      robot.flangePositionM[0], robot.flangePositionM[1], this.safeTransitZM,
    ];
    if (!this._withinWorkspace(position) ||
        distance(position, robot.flangePositionM) > this.maxCoarseTranslationM) {
      return this._abort('safe_height_out_of_workspace');
    }
    return this._sendMove('moving_to_safe_height', position);
  }

  _sendOverPregrasp(pointM) {
    const robot = this.getRobotState();
    const pregrasp = this._pregrasp(pointM);
    if (this.safeTransitZM < pregrasp[2] + 0.05) {
      return this._abort('safe_transit_clearance_insufficient');
    }
    const position = [pregrasp[0], pregrasp[1], this.safeTransitZM];
    if (!this._withinWorkspace(position) ||
        distance(position, robot.flangePositionM) > this.maxCoarseTranslationM) {
      return this._abort('over_pregrasp_out_of_workspace');
    }
    return this._sendMove('moving_over_pregrasp', position);
  }

  _refineOrHandoff(observed) {
    const robot = this.getRobotState();
    const desired = this._pregrasp(observed.pointM);
    const error = desired.map((value, index) => value - robot.flangePositionM[index]);
    const errorM = Math.hypot(...error);
    if (errorM <= this.alignmentToleranceM) {
      const target = observed.target;
      const preview = previewOf(target);
      const handoff = {
        actionable: target.actionable === true,
        stableId: this.session.targetId,
        requestId: this.session.requestId,
        evidenceId: target.evidenceId,
        motionEpoch: this.session.motionEpoch,
        trackState: target.trackState,
        depthValid: target.depthValid === true,
        blockers: Array.isArray(target.blockers) ? [...target.blockers] : [],
        observedAtMs: target.observedAtMs,
        posePositionStdM: target.posePositionStdM,
        calibrationValidated: target.calibrationValidated === true,
        safetyApproved: target.safetyApproved === true,
        armStationary: target.armStationary === true,
        gripperReady: target.gripperReady === true,
        calibrationId: this.targetLock.snapshot().calibrationId,
        visionConfigId: target.visionConfigId,
        modelProvenance: target.modelProvenance,
        sourceVisionEvidenceIds: observed.sourceVisionEvidenceIds,
        sourcePreviewIds: observed.sourcePreviewIds,
        sourceArmStateIds: observed.sourceArmStateIds,
        sourceObservedAtMs: observed.sourceObservedAtMs,
        baseSpreadM: observed.spreadM ?? 0,
        previewId: preview?.previewId ?? preview?.preview_id,
        detectedGraspPointM: [...observed.pointM],
        commandedFlangeGraspM: this._corrected(observed.pointM),
        flangeOffsetBaseM: [...this.graspOffsetBaseM],
        approachBase: preview?.approachBase ?? preview?.approach_base ?? [1, 0, 0],
        widthM: preview?.widthM ?? preview?.width_m,
        eulerRad: preview?.eulerRad ?? preview?.euler_rad ?? this.horizontalEulerRad,
      };
      if (typeof handoff.evidenceId !== 'string' ||
          !vector3(handoff.detectedGraspPointM) ||
          !vector3(handoff.commandedFlangeGraspM)) {
        return this._abort('fresh_evidence_invalid');
      }
      const result = this.startGrasp(handoff);
      if (result?.accepted !== true) {
        return this._abort(result?.reason || 'grasp_handoff_failed');
      }
      this.session.phase = 'handed_off';
      this._publish();
      return { handled: true, accepted: true, phase: 'handed_off', grasp: result };
    }
    if (this.session.refineSteps >= this.maxRefineSteps) {
      return this._abort('refine_step_limit');
    }
    const step = clampVector(error, this.maxRefineStepM);
    const position = robot.flangePositionM.map((value, index) => value + step[index]);
    if (!this._withinWorkspace(position)) return this._abort('refine_step_out_of_workspace');
    this.session.refineSteps += 1;
    return this._sendMove('refining', position);
  }

  _sendMove(phase, position) {
    const requestId = this.idFactory();
    if (!UUID_PATTERN.test(requestId)) return this._abort('request_id_invalid');
    const robot = this.getRobotState();
    const timeSec = Math.max(
      1.0,
      Number((distance(position, robot.flangePositionM) / this.linearSpeedMps).toFixed(3))
    );
    const command = {
      cmd: 'move_l',
      position: [...position],
      euler: [...this.horizontalEulerRad],
      time_sec: timeSec,
      request_id: requestId,
      source: `visual_align:${phase}`,
    };
    if (this.sendRobot(command) !== true) return this._abort('robot_transport_unavailable');
    this.inFlight = { phase, requestId };
    this.session.phase = phase;
    this._publish();
    return { handled: true, accepted: true, phase, requestId, positionM: [...position] };
  }

  _abort(reason) {
    if (!this.session) return { accepted: false, reason };
    this.inFlight = null;
    this.session.phase = 'aborted';
    this.session.reason = reason;
    this._publish();
    return { handled: true, accepted: false, reason, phase: 'aborted' };
  }

  _publish() {
    this.onStatus(this.snapshot());
  }
}

module.exports = { VisualAlignController, clampVector };
