'use strict';

const { EventEmitter } = require('node:events');
const { createHash, randomUUID } = require('node:crypto');
const { planAlignmentStep } = require('./candidate');
const { streamPixelToRay } = require('./fisheye');

const TERMINAL_PHASES = new Set(['depth_acquired', 'failed', 'stopped', 'uncertain']);
const DEPTH_CENTER_PIXEL = Object.freeze([315.5, 234]);
const DEPTH_CENTER_TOLERANCE_PX = 20;
const DEFAULT_LIMITS = Object.freeze({
  jointLimitsDeg: [[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],
  maxStepDeg: 4, maxCumulativeJointDeg: 20,
  maxArmStepDeg: 2, maxArmCumulativeJointDeg: 10,
  maxCameraStepM: 0.01, maxCameraCumulativeM: 0.04,
});

function coordinatorError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function finiteVector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function robotReady(robot) {
  return finiteVector(robot?.jointsDeg, 6) && robot.stateName === 'IDLE'
    && robot.motionActive !== true && robot.moving !== true
    && (!Object.prototype.hasOwnProperty.call(robot, 'connected') || robot.connected === true)
    && (!Object.prototype.hasOwnProperty.call(robot, 'stateFresh') || robot.stateFresh === true);
}

function bearingError(pixel) {
  const measured = streamPixelToRay(pixel);
  const desired = streamPixelToRay(DEPTH_CENTER_PIXEL);
  if (!measured.ok || !desired.ok) return Infinity;
  const dot = measured.ray.reduce((sum, value, index) => sum + value * desired.ray[index], 0);
  return Math.acos(Math.max(-1, Math.min(1, dot)));
}

function centerErrorPx(pixel) {
  return Math.hypot(
    pixel[0] - DEPTH_CENTER_PIXEL[0],
    pixel[1] - DEPTH_CENTER_PIXEL[1],
  );
}

function immutableStatus(status) {
  const copy = {
    type: 'active_depth.status', ...status,
    targetPixel: Array.isArray(status.targetPixel) ? [...status.targetPixel] : null,
    predictedPixel: Array.isArray(status.predictedPixel) ? [...status.predictedPixel] : null,
    jointDeltasDeg: Array.isArray(status.jointDeltasDeg) ? [...status.jointDeltasDeg] : null,
  };
  return Object.freeze(copy);
}

class ActiveDepthCoordinator extends EventEmitter {
  constructor({ visionClient, executionClient, getRobotState, mount,
    planStep = planAlignmentStep, limits = DEFAULT_LIMITS,
    pollIntervalMs = 100, now = Date.now, sleep = delay }) {
    super();
    this.visionClient = visionClient;
    this.executionClient = executionClient;
    this.getRobotState = getRobotState;
    this.mount = mount;
    this.planStep = planStep;
    this.limits = limits;
    this.pollIntervalMs = pollIntervalMs;
    this.now = now;
    this.sleep = sleep;
    this.session = null;
    this.currentStatus = immutableStatus({
      phase: 'idle', active: false, sessionId: null, stableId: null,
      depthValidFrames: 0, completedSteps: 0, reason: null,
    });
  }

  status() {
    return this.currentStatus;
  }

  _publish(changes) {
    this.currentStatus = immutableStatus({ ...this.currentStatus, ...changes });
    this.emit('status', this.currentStatus);
    return this.currentStatus;
  }

  async start(stableId) {
    if (!Number.isSafeInteger(stableId) || stableId < 1 || stableId > 5) {
      throw coordinatorError('stable_id_invalid', 'Stable target ID must be within 1..5');
    }
    if (this.session && !TERMINAL_PHASES.has(this.currentStatus.phase)) {
      throw coordinatorError('active_depth_active', 'An active-depth session is already running');
    }
    const robot = this.getRobotState();
    if (!robotReady(robot)) {
      throw coordinatorError('robot_not_stationary', 'Robot state is not stationary and ready');
    }
    const sessionId = randomUUID();
    this.session = {
      sessionId, stableId, startedAtMs: this.now(), startJointsDeg: [...robot.jointsDeg],
      completedSteps: 0, depthValidFrames: 0, lastFrameId: null,
      stopRequested: false, inFlight: false, terminal: false,
      previousStep: null, noProgressSteps: 0,
    };
    this._publish({
      phase: 'observing', active: true, sessionId, stableId,
      depthValidFrames: 0, completedSteps: 0, reason: null,
      targetPixel: null, predictedPixel: null, jointDeltasDeg: null,
      cameraShiftM: null, tier: null,
    });
    this._run(this.session).catch(error => {
      if (this.session === null || this.session.terminal) return;
      this._terminal('failed', error.code || 'active_depth_internal_error');
    });
    return this.currentStatus;
  }

  _terminal(phase, reason) {
    const session = this.session;
    if (!session || session.terminal) return this.currentStatus;
    session.terminal = true;
    return this._publish({ phase, active: false, reason });
  }

  _targetFor(observation, stableId) {
    if (Number(observation?.selectedStableId) !== stableId) return null;
    const matches = (observation.targets || []).filter(target =>
      Number(target.stable_id ?? target.stableId) === stableId);
    return matches.length === 1 ? matches[0] : null;
  }

  async _run(session) {
    while (!session.terminal && !session.stopRequested) {
      const elapsedMs = this.now() - session.startedAtMs;
      if (elapsedMs >= 90000) { this._terminal('failed', 'time_limit'); return; }
      if (session.completedSteps >= 20) { this._terminal('failed', 'step_limit'); return; }
      let snapshot;
      try { snapshot = await this.visionClient.snapshot(session.stableId); }
      catch (error) { this._terminal('failed', error.code || 'vision_unavailable'); return; }
      if (session.stopRequested || session.terminal) return;
      const { observation, runtimeEvidence = {} } = snapshot;
      const frameId = Number(observation?.frameId ?? observation?.frame_id);
      if (!Number.isSafeInteger(frameId) || frameId < 0) {
        this._terminal('failed', 'vision_frame_invalid'); return;
      }
      if (session.lastFrameId !== null && frameId <= session.lastFrameId) {
        await this.sleep(this.pollIntervalMs);
        continue;
      }
      session.lastFrameId = frameId;
      const target = this._targetFor(observation, session.stableId);
      if (!target) { this._terminal('failed', 'target_switched'); return; }
      if (target.track_state !== undefined && target.track_state !== 'confirmed') {
        this._terminal('failed', 'target_not_confirmed'); return;
      }
      if ((runtimeEvidence.camera_mount_id || observation.camera_mount_id) !== this.mount.camera_mount_id
          || (runtimeEvidence.registration_id || observation.registration_id) !== this.mount.registration_id) {
        this._terminal('failed', 'camera_evidence_mismatch'); return;
      }
      const targetPixel = target.centroid_xy ?? target.centroidXY;
      if (!finiteVector(targetPixel, 2)) { this._terminal('failed', 'target_pixel_invalid'); return; }
      const depthValid = target.depth_valid === true && finiteVector(target.camera_xyz_m, 3);
      const pixelError = centerErrorPx(targetPixel);
      const centeredDepth = depthValid && pixelError <= DEPTH_CENTER_TOLERANCE_PX;
      session.depthValidFrames = centeredDepth ? session.depthValidFrames + 1 : 0;
      this._publish({
        phase: 'observing', active: true, targetPixel,
        centerErrorPx: pixelError, centered: centeredDepth,
        depthValidFrames: session.depthValidFrames,
        completedSteps: session.completedSteps,
      });
      if (session.depthValidFrames >= 3) {
        this._terminal('depth_acquired', 'depth_valid_three_frames'); return;
      }
      if (centeredDepth) { await this.sleep(this.pollIntervalMs); continue; }

      let forceArmFallback = false;
      if (session.previousStep) {
        const observedError = bearingError(targetPixel);
        if (!Number.isFinite(observedError)) {
          this._terminal('failed', 'no_progress'); return;
        }
        if (session.previousStep.beforeAngularError - observedError < 0.001) {
          session.noProgressSteps += 1;
        } else {
          session.noProgressSteps = 0;
        }
        if (session.noProgressSteps >= 3 && session.previousStep.tier === 'arm_fallback') {
          this._terminal('failed', 'no_progress'); return;
        }
        forceArmFallback = session.noProgressSteps >= 2;
        session.previousStep = null;
      }
      const robot = this.getRobotState();
      if (!robotReady(robot)) {
        this._terminal('failed', 'robot_not_stationary'); return;
      }
      const plan = this.planStep({
        targetPixel, jointsDeg: robot.jointsDeg, startJointsDeg: session.startJointsDeg,
        tFlangeCamera: this.mount.matrix_4x4,
        limits: { ...this.limits, jointLimitsDeg: robot.jointLimitsDeg || this.limits.jointLimitsDeg },
        completedSteps: session.completedSteps, elapsedMs, forceArmFallback,
      });
      if (!plan.ok) { this._terminal('failed', plan.reason || 'no_candidate'); return; }
      const primitiveId = randomUUID();
      const planDigest = `sha256:${createHash('sha256').update(JSON.stringify(plan)).digest('hex')}`;
      const evidenceId = observation.evidence_id ?? observation.evidenceId;
      if (!/^sha256:[0-9a-f]{64}$/.test(String(evidenceId))) {
        this._terminal('failed', 'evidence_invalid'); return;
      }
      const primitive = {
        schema: 'thirdhand.execution-primitive.v1', primitiveId,
        traceId: session.sessionId, taskId: `active-depth:${session.sessionId}`,
        authorizationId: `active-depth:${session.sessionId}`, planDigest,
        operation: 'vision.align.step', parameters: {
          sessionId: session.sessionId, stableId: session.stableId, frameId,
          evidenceId, motionEpoch: Number(observation.motion_epoch ?? observation.motionEpoch ?? 0),
          tier: plan.tier, wristExhausted: plan.wristExhausted,
          startJointsDeg: [...robot.jointsDeg], targetJointsDeg: [...plan.targetJointsDeg],
          timeoutMs: 5000,
        },
      };
      session.inFlight = true;
      this._publish({
        phase: 'moving', active: true, tier: plan.tier,
        predictedPixel: plan.predictedPixel, jointDeltasDeg: plan.jointDeltasDeg,
        cameraShiftM: plan.cameraShiftM,
      });
      let result;
      try { result = await this.executionClient.execute(primitive); }
      catch (error) {
        session.inFlight = false;
        if (!session.stopRequested) this._terminal('uncertain', error.code || 'execution_uncertain');
        return;
      }
      session.inFlight = false;
      if (session.stopRequested || session.terminal) return;
      if (result.status !== 'completed' || result.primitiveId !== primitiveId) {
        this._terminal(result.status === 'uncertain' ? 'uncertain' : 'failed',
          result.code || 'execution_failed');
        return;
      }
      session.completedSteps += 1;
      session.previousStep = { beforeAngularError: bearingError(targetPixel), tier: plan.tier };
      await this.sleep(this.pollIntervalMs);
    }
  }

  async stop(sessionId) {
    const session = this.session;
    if (!session || session.sessionId !== sessionId || session.terminal) return this.currentStatus;
    session.stopRequested = true;
    if (session.inFlight) {
      let result;
      try { result = await this.executionClient.stop(session.sessionId); }
      catch { return this._terminal('uncertain', 'stop_uncertain'); }
      if (result?.status !== 'interrupted') {
        return this._terminal('uncertain', result?.code || 'stop_uncertain');
      }
    }
    return this._terminal('stopped', 'operator_stop');
  }

  async close() {
    if (this.session && !this.session.terminal) await this.stop(this.session.sessionId);
    this.executionClient.close();
  }
}

module.exports = { ActiveDepthCoordinator, DEFAULT_LIMITS, TERMINAL_PHASES };
