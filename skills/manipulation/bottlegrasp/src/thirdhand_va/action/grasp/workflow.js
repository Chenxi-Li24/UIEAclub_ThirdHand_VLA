'use strict';

const { randomUUID } = require('node:crypto');

const { VisualAlignController } = require('../alignment/visual_align_controller');
const { GraspController } = require('./grasp_controller');
const { buildExecutionPlan, deriveExecutionGeometry } = require('./execution_plan');
const { VisionClient } = require('../adapters/vision_client');
const { evaluateExecutionGate } = require('../safety/execution_gate');
const { evaluateHomeState } = require('../safety/home_gate');
const { buildActionEvidence } = require('../evidence/action_evidence');
const {
  copyRuntimeEvidence,
  sameRuntimeEvidence,
  validRuntimeEvidence,
  visionResultMatchesRuntime,
} = require('../runtime/approved_runtime');

class WorkflowClient {
  constructor({
    cameraBridge,
    robotClient,
    config,
    store = { write() {} },
    planBuilder = null,
    createAlignmentController = dependencies => new VisualAlignController(dependencies),
    createGraspController = dependencies => new GraspController(dependencies),
    onFinish = () => {},
    workflowTimeoutMs = 240000,
    stopAckTimeoutMs = 2000,
    releaseAckTimeoutMs = 2000,
    stopIdFactory = randomUUID,
    nowMs = Date.now,
    runtimeEvidence = null,
    approvedRuntimeEvidence = null,
  } = {}) {
    if (!cameraBridge || typeof cameraBridge.send !== 'function' ||
        typeof cameraBridge.on !== 'function') {
      throw new TypeError('cameraBridge.send/on are required');
    }
    if (!robotClient || typeof robotClient.send !== 'function' ||
        typeof robotClient.getRobotState !== 'function' || !config ||
        typeof store.write !== 'function' ||
        !(planBuilder === null || typeof planBuilder === 'function') ||
        typeof createAlignmentController !== 'function' ||
        typeof createGraspController !== 'function' || typeof onFinish !== 'function' ||
        !Number.isFinite(workflowTimeoutMs) || workflowTimeoutMs <= 0 ||
        !Number.isFinite(stopAckTimeoutMs) || stopAckTimeoutMs <= 0 ||
        !Number.isFinite(releaseAckTimeoutMs) || releaseAckTimeoutMs <= 0 ||
        typeof stopIdFactory !== 'function' ||
        !(runtimeEvidence === null || typeof runtimeEvidence === 'function') ||
        (runtimeEvidence !== null && !validRuntimeEvidence(approvedRuntimeEvidence)) ||
        (runtimeEvidence === null && approvedRuntimeEvidence !== null)) {
      throw new TypeError('workflow dependencies are invalid');
    }
    this.cameraBridge = cameraBridge;
    this.robotClient = robotClient;
    this.config = config;
    this.store = store;
    this.planBuilder = planBuilder;
    this.onFinish = onFinish;
    this.workflowTimeoutMs = workflowTimeoutMs;
    this.stopAckTimeoutMs = stopAckTimeoutMs;
    this.releaseAckTimeoutMs = releaseAckTimeoutMs;
    this.stopIdFactory = stopIdFactory;
    this.nowMs = nowMs;
    this.runtimeEvidence = runtimeEvidence;
    this.approvedRuntimeEvidence = approvedRuntimeEvidence === null
      ? null : copyRuntimeEvidence(approvedRuntimeEvidence);
    this.runtimeEvidenceAtStart = null;
    this.session = null;
    this.timer = null;
    this.stopTimer = null;
    this.releaseTimer = null;
    this.stopPending = null;
    this.finishing = null;
    this.finished = false;

    this.grasp = createGraspController({
      robotClient,
      getRobotState: () => robotClient.getRobotState(),
      onStatus: status => this._onGraspStatus(status),
    });
    this.alignment = createAlignmentController({
      executionEnabled: config.execution_enabled === true,
      getRobotState: () => robotClient.getRobotState(),
      selectBottle: message => cameraBridge.send(message),
      resetTargetPoseReference: message => cameraBridge.send(message),
      sendRobot: command => robotClient.send(command),
      startGrasp: handoff => this._startGrasp(handoff),
      onStatus: status => this._onAlignmentStatus(status),
      nowMs,
      workspace: config.workspace_m,
      alignStandoffM: config.motion?.pregrasp_offset_m,
      safeTransitZM: config.motion?.safe_transit_z_m ?? null,
      maxRefineStepM: config.motion?.max_refine_step_m,
      horizontalEulerRad: config.motion?.grasp_euler_rad,
      linearSpeedMps: config.motion?.linear_speed_m_s,
      graspOffsetBaseM: config.grasp?.flange_offset_base_m,
    });
    this.visionClient = new VisionClient();
    this.visionClient.on('result', result => this.onVisionResult(result));
    this._cameraListener = event => this.visionClient.accept(event);
    this._cameraReleaseListener = event => this._onReleaseStatus(event);
    this._robotListener = event => this.onRobotEvent(event);
    cameraBridge.on?.('detection_result', this._cameraListener);
    cameraBridge.on('selection_release_status', this._cameraReleaseListener);
    robotClient.on?.('event', this._robotListener);
  }

  start({ targetId, requestId } = {}) {
    if (this.session !== null && !this.finished) {
      return { accepted: false, reason: 'workflow_active' };
    }
    if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5 ||
        typeof requestId !== 'string' || !requestId) {
      return { accepted: false, reason: 'workflow_request_invalid' };
    }
    const homePreset = this.config.place?.home_preset;
    const home = evaluateHomeState({
      robotState: this.robotClient.getRobotState(),
      homeJointsDeg: this.config.robot?.presets?.[homePreset],
      toleranceDeg: this.config.robot?.home_tolerance_deg,
    });
    if (home.allowed !== true) {
      return { accepted: false, reason: home.blockers[0] || 'robot_not_at_home' };
    }
    if (this.runtimeEvidence !== null) {
      const currentRuntime = this.runtimeEvidence();
      if (!sameRuntimeEvidence(currentRuntime, this.approvedRuntimeEvidence)) {
        return { accepted: false, reason: 'runtime_artifact_not_approved' };
      }
      this.runtimeEvidenceAtStart = copyRuntimeEvidence(currentRuntime);
    } else {
      this.runtimeEvidenceAtStart = null;
    }
    this.session = {
      targetId, requestId, phase: 'starting', evidenceId: null, actionEvidence: null,
    };
    this.finished = false;
    const result = this.alignment.start({ targetId, requestId });
    if (result?.accepted !== true) {
      this._finish(false, result?.reason ?? 'alignment_start_failed');
      return result;
    }
    this.timer = setTimeout(
      () => this.cancel('workflow_timeout'), this.workflowTimeoutMs
    );
    this.timer.unref?.();
    this._write('alignment', { phase: result.phase });
    return { accepted: true, targetId, requestId, phase: result.phase };
  }

  onVisionResult(result) {
    if (!this.session || this.finished || this.finishing !== null) {
      return { handled: false, reason: 'workflow_inactive' };
    }
    if (this.runtimeEvidence !== null && (
      !sameRuntimeEvidence(this.runtimeEvidenceAtStart, this.runtimeEvidence()) ||
      !visionResultMatchesRuntime(result, this.runtimeEvidenceAtStart)
    )) return this.cancel('runtime_artifact_mismatch');
    return this.alignment.onVisionTargets(this._normalizeVisionTargets(result));
  }

  onRobotEvent(event) {
    if (event?.type === 'robot_state') this._forwardArmState(event);
    if (!this.session || this.finished || this.finishing !== null) {
      return { handled: false, reason: 'workflow_inactive' };
    }
    if (this.stopPending !== null) {
      if (event?.type === 'robot_state') {
        if (this.stopPending.acknowledged !== true) {
          return { handled: false, reason: 'stop_ack_pending' };
        }
        return this._confirmStoppedState();
      }
      if (event?.request_id !== this.stopPending.requestId ||
          event?.command !== 'software_stop' ||
          !['command_complete', 'error'].includes(event?.type)) {
        return { handled: false, reason: 'stop_ack_not_matched' };
      }
      if (this.robotClient.stopProofMode === 'cleanup_ack_only') {
        const pending = this.stopPending;
        if (event.type !== 'command_complete' ||
            event.cleanupAcknowledged !== true ||
            !['simulation', 'vendor_cleanup_returned'].includes(
              event.cleanupConfirmationMode
            ) || event.controlReleased !== true ||
            event.depowerIndependentlyConfirmed !== false) {
          this.stopPending = null;
          this._finish(false, 'software_stop_not_confirmed');
          return {
            handled: true, accepted: false, reason: 'software_stop_not_confirmed',
          };
        }
        this.stopPending = null;
        if (this.stopTimer) clearTimeout(this.stopTimer);
        this.stopTimer = null;
        this._finish(false, pending.reason);
        return { handled: true, accepted: true, reason: pending.reason };
      }
      if (this.robotClient.stopProofMode !== 'fresh_state_boundary') {
        this.stopPending = null;
        this._finish(false, 'software_stop_not_confirmed');
        return { handled: true, accepted: false, reason: 'software_stop_not_confirmed' };
      }
      if (event.type !== 'command_complete' || event.stopped !== true ||
          !Number.isSafeInteger(event.applied_state_sequence) ||
          event.applied_state_sequence < 0 ||
          !Number.isSafeInteger(event.applied_producer_monotonic_ns) ||
          event.applied_producer_monotonic_ns < 0) {
        this.stopPending = null;
        this._finish(false, 'software_stop_not_confirmed');
        return { handled: true, accepted: false, reason: 'software_stop_not_confirmed' };
      }
      this.stopPending.acknowledged = true;
      this.stopPending.appliedStateSequence = event.applied_state_sequence;
      this.stopPending.appliedProducerMonotonicNs =
        event.applied_producer_monotonic_ns;
      return { handled: true, accepted: true, reason: 'fresh_stopped_state_pending' };
    }
    if (this.grasp.active) return this.grasp.onRobotEvent(event);
    return this.alignment.onRobotEvent(event);
  }

  cancel(reason = 'operator_cancelled') {
    if (!this.session || this.finished) return { accepted: false, reason: 'workflow_inactive' };
    if (this.finishing !== null) {
      return { accepted: true, duplicate: true, reason: 'release_confirmation_pending' };
    }
    if (this.stopPending !== null) {
      return { accepted: true, duplicate: true, reason: 'stop_requested',
        stopRequestId: this.stopPending.requestId };
    }
    const stopRequestId = this.stopIdFactory();
    if (typeof stopRequestId !== 'string' || !stopRequestId) {
      this._finish(false, 'software_stop_request_id_invalid');
      return { accepted: false, reason: 'software_stop_request_id_invalid' };
    }
    this.stopPending = {
      requestId: stopRequestId, reason, acknowledged: false,
      appliedStateSequence: null, appliedProducerMonotonicNs: null,
    };
    const stopSent = this.robotClient.send({
      cmd: 'software_stop', source: 'workflow:cancel', reason,
      request_id: stopRequestId,
    }) === true;
    if (!stopSent) {
      this.stopPending = null;
      if (this.grasp.active) this.grasp.cancel('software_stop_transport_unavailable');
      else if (this.alignment.active) {
        this.alignment.cancel('software_stop_transport_unavailable');
      }
      this._finish(false, 'software_stop_transport_unavailable');
      return { accepted: false, reason: 'software_stop_transport_unavailable' };
    }
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.grasp.active) this.grasp.cancel(reason);
    else if (this.alignment.active) this.alignment.cancel(reason);
    if (this.session && !this.finished) this.session.phase = 'stopping';
    this._write('stopping', { reason, stop_request_id: stopRequestId });
    this.stopTimer = setTimeout(() => {
      this.stopPending = null;
      this.stopTimer = null;
      this._finish(false, 'software_stop_not_confirmed');
    }, this.stopAckTimeoutMs);
    this.stopTimer.unref?.();
    return { accepted: true, reason: 'stop_requested', stopRequestId };
  }

  snapshot() {
    return Object.freeze({
      active: this.session !== null && !this.finished,
      targetId: this.session?.targetId ?? null,
      requestId: this.session?.requestId ?? null,
      phase: this.session?.phase ?? 'idle',
      evidenceId: this.session?.evidenceId ?? null,
    });
  }

  _startGrasp(handoff) {
    let plan;
    try {
      if (this.planBuilder !== null) {
        plan = this.planBuilder(handoff, this.config);
      } else {
        const actionEvidence = buildActionEvidence({
          ...handoff,
          actionConfigId: this.config.content_id,
          pathValidationId: this.config.place?.path_validation_id,
          flangeOffsetBaseM: this.config.grasp?.flange_offset_base_m,
        });
        handoff = {
          ...handoff,
          evidenceId: actionEvidence.id,
          actionEvidence,
        };
        const robot = this.robotClient.getRobotState();
        const geometry = deriveExecutionGeometry(handoff, this.config);
        const gate = evaluateExecutionGate({
          executionEnabled: this.config.execution_enabled,
          visionReady: handoff.actionable,
          requestedStableId: this.session.targetId,
          targetStableId: handoff.stableId,
          trackState: handoff.trackState,
          evidenceId: handoff.evidenceId,
          evidenceAgeMs: this.nowMs() - handoff.observedAtMs,
          maxEvidenceAgeMs: 500,
          evidenceMotionEpoch: handoff.motionEpoch,
          motionEpoch: this.alignment.snapshot?.().motionEpoch ?? handoff.motionEpoch,
          depthValid: handoff.depthValid,
          posePositionStdM: handoff.posePositionStdM,
          maxPositionStdM: 0.010,
          calibrationValidated: handoff.calibrationValidated,
          armStationary: handoff.armStationary && robot?.stationary === true,
          safetyApproved: handoff.safetyApproved,
          gripperReady: handoff.gripperReady && Number.isFinite(robot?.gripperWidthM),
          placeValidated: this.config.place?.validated,
          graspOffsetValidated: this.config.grasp?.offset_validated,
          widthM: handoff.widthM,
          maxWidthM: this.config.gripper?.execution_max_width_m,
          pregraspM: geometry.pregraspM,
          commandedFlangeGraspM: geometry.commandedFlangeGraspM,
          liftM: geometry.liftM,
          prePlaceM: geometry.prePlaceM,
          placeM: geometry.placeM,
          retreatM: geometry.retreatM,
          workspace: this.config.workspace_m,
        });
        if (!gate.allowed) throw new Error(gate.blockers[0] || 'execution_blocked');
        plan = buildExecutionPlan(handoff, this.config);
      }
    } catch (error) {
      return { accepted: false, reason: error.message || 'execution_plan_failed' };
    }
    this.session.evidenceId = plan.evidenceId ?? handoff.evidenceId ?? null;
    this.session.actionEvidence = plan.actionEvidence ?? handoff.actionEvidence ?? null;
    const result = this.grasp.start(plan);
    if (result?.accepted !== true) return result;
    if (!this.finished) {
      this.session.phase = 'grasp';
      this._write('grasp', { phase: result.phase });
    }
    return result;
  }

  _onAlignmentStatus(status) {
    if (!this.session || this.finished || this.finishing !== null) return;
    this.session.phase = `alignment:${status.phase}`;
    this._write('alignment', status);
    if (this.stopPending !== null) return;
    if (status.phase === 'aborted') this._finish(false, status.reason || 'alignment_aborted');
  }

  _onGraspStatus(status) {
    if (!this.session || this.finished || this.finishing !== null) return;
    this.session.phase = `grasp:${status.phase}`;
    this._write('grasp', status);
    if (this.stopPending !== null) return;
    if (status.phase === 'complete') this._finish(true, null);
    else if (['failed', 'manual_recovery', 'cancelled'].includes(status.phase)) {
      this._finish(false, status.reason || status.phase);
    }
  }

  _normalizeVisionTargets(result) {
    if (!result || !Array.isArray(result.targets)) return [];
    return result.targets.map(target => {
      if (target.requestId && target.motionEpoch !== undefined) return target;
      const preview = target.graspPreview ?? null;
      return {
        ...target,
        requestId: result.requestId,
        calibrationId: preview?.calibration_id ?? preview?.calibrationId ?? null,
        motionEpoch: result.motionEpoch,
        armStationary: !preview?.blockers?.includes('arm_not_stationary'),
        observedAtMs: result.observedAtMs ?? this.nowMs(),
        evidenceId: result.evidenceId,
        visionConfigId: result.visionConfigId,
        modelProvenance: result.modelProvenance,
        actionable: target.actionable === true,
        posePositionStdM: result.pose?.positionStdM ?? null,
        calibrationValidated: target.calibrationValidated === true ||
          preview?.allowed === true,
        safetyApproved: target.safetyApproved === true || preview?.allowed === true,
        gripperReady: Number.isFinite(this.robotClient.getRobotState()?.gripperWidthM),
        preview: preview === null ? null : {
          previewId: preview.preview_id ?? preview.previewId,
          pointM: preview.grasp_xyz_m ?? preview.pointM,
          stableSamples: preview.stable_samples ?? preview.stableSamples,
          widthM: preview.width_m ?? preview.widthM,
          approachBase: preview.approach_base ?? preview.approachBase,
          calibrationId: preview.calibration_id ?? preview.calibrationId,
          allowed: preview.allowed === true,
          blockers: Array.isArray(preview.blockers) ? [...preview.blockers] : [],
          armStateId: preview.arm_state_id ?? preview.armStateId,
          armState: preview.arm_state ?? preview.armState,
          visionEvidenceId: preview.vision_evidence_id ?? preview.visionEvidenceId,
          visionConfigId: preview.vision_config_id ?? preview.visionConfigId,
          modelProvenance: preview.model_provenance ?? preview.modelProvenance,
        },
      };
    });
  }

  _confirmStoppedState() {
    const pending = this.stopPending;
    const robot = this.robotClient.getRobotState();
    const observed = robot?.observedMonotonicNs;
    const sequence = robot?.stateSequence;
    const producerNs = robot?.producerMonotonicNs;
    const afterAck = Number.isSafeInteger(observed) &&
      Number.isSafeInteger(sequence) && Number.isSafeInteger(producerNs) &&
      Number.isSafeInteger(pending?.appliedStateSequence) &&
      Number.isSafeInteger(pending?.appliedProducerMonotonicNs) &&
      sequence > pending.appliedStateSequence &&
      producerNs > pending.appliedProducerMonotonicNs;
    if (pending?.acknowledged !== true || !afterAck ||
        robot?.connected !== true || robot.stateFresh !== true ||
        robot.stationary !== true) {
      return { handled: false, reason: 'fresh_stopped_state_pending' };
    }
    this.stopPending = null;
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.stopTimer = null;
    this._finish(false, pending.reason);
    return { handled: true, accepted: true, reason: pending.reason };
  }

  _forwardArmState(state) {
    if (typeof this.cameraBridge.sendArmState !== 'function') return;
    this.cameraBridge.sendArmState(
      state.flangePositionM,
      state.flangeEulerRad,
      state.jointsDeg,
      state.velocitiesDegS,
      state.stationary,
      state.observedMonotonicNs,
    );
  }

  _write(state, details = {}) {
    this.store.write({
      schema: 'thirdhand.va.status.v1',
      state,
      target_id: this.session?.targetId ?? null,
      request_id: this.session?.requestId ?? null,
      ...details,
    });
  }

  _finish(ok, reason) {
    if (this.finished || this.finishing !== null) return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    if (this.stopTimer) clearTimeout(this.stopTimer);
    this.stopTimer = null;
    this.stopPending = null;
    this.finishing = { ok: ok === true, reason };
    if (this.session === null) {
      this._completeFinish(true, null);
      return;
    }
    this.session.phase = 'releasing_reservation';
    this._write('releasing_reservation', { result_ok: ok === true, reason });
    const releaseSent = this.cameraBridge.send({
      type: 'release_bottle', request_id: this.session.requestId,
    }) === true;
    if (!releaseSent) {
      this._completeFinish(false, 'vision_release_transport_unavailable');
      return;
    }
    // A memory adapter may acknowledge synchronously from send().
    if (this.finishing === null || this.finished) return;
    this.releaseTimer = setTimeout(() => {
      this.releaseTimer = null;
      this._completeFinish(false, 'vision_release_not_confirmed');
    }, this.releaseAckTimeoutMs);
    this.releaseTimer.unref?.();
  }

  _onReleaseStatus(event) {
    if (this.finishing === null || this.finished || !this.session ||
        event?.type !== 'selection_release_status' ||
        event.request_id !== this.session.requestId) return false;
    const confirmed = event.status === 'released' || event.status === 'not_reserved';
    this._completeFinish(
      confirmed,
      confirmed ? null : 'vision_release_not_confirmed',
    );
    return true;
  }

  _completeFinish(releaseSucceeded, cleanupReason) {
    if (this.finishing === null || this.finished) return;
    const pending = this.finishing;
    this.finishing = null;
    this.finished = true;
    if (this.releaseTimer) clearTimeout(this.releaseTimer);
    this.releaseTimer = null;
    this.cameraBridge.off?.('detection_result', this._cameraListener);
    this.cameraBridge.off?.('selection_release_status', this._cameraReleaseListener);
    const finalOk = pending.ok === true && releaseSucceeded === true;
    const finalReason = pending.ok === true && !releaseSucceeded
      ? cleanupReason : pending.reason;
    const result = Object.freeze({
      ok: finalOk,
      targetId: this.session?.targetId ?? null,
      requestId: this.session?.requestId ?? null,
      evidenceId: this.session?.evidenceId ?? null,
      actionEvidence: this.session?.actionEvidence ?? null,
      phase: finalOk ? 'complete' : 'failed',
      reason: finalReason,
      releaseSucceeded,
      cleanupReason,
    });
    if (this.session) this.session.phase = result.phase;
    this._write(result.phase, result);
    this.onFinish(result);
  }
}

module.exports = {
  WorkflowClient, sameRuntimeEvidence, validRuntimeEvidence, visionResultMatchesRuntime,
};
