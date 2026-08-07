'use strict';

function finiteOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nonNegativeIntegerOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= 0 ? number : null;
}

function boundedStrings(value, limit = 64) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter(item => typeof item === 'string' && item).slice(0, limit))];
}

function finitePosition(value) {
  if (!Array.isArray(value) || value.length !== 3) return null;
  const result = value.map(Number);
  return result.every(Number.isFinite) ? result : null;
}

function finiteXY(value) {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const result = value.map(Number);
  return result.every(Number.isFinite) ? result : null;
}

function boundedString(value, limit = 128) {
  return typeof value === 'string' && value ? value.slice(0, limit) : null;
}

function positionStandardDeviation(value) {
  if (!Array.isArray(value) || value.length !== 3 ||
      value.some(row => !Array.isArray(row) || row.length !== 3)) return null;
  const covariance = value.map(row => row.map(Number));
  if (!covariance.flat().every(Number.isFinite)) return null;
  const diagonal = covariance.map((row, index) => row[index]);
  if (diagonal.some(item => item < 0)) return null;
  return diagonal.map(Math.sqrt);
}

function shortCalibrationId(value) {
  if (typeof value !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(value)) return null;
  return `${value.slice(0, 19)}…`;
}

function sanitizeGraspPreview(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const pointPx = finiteXY(value.pixel_xy);
  const pointM = finitePosition(value.xyz_m);
  if (pointPx === null && pointM === null) return null;
  return {
    pointPx,
    pointM,
    frame: boundedString(value.frame, 64),
    status: boundedString(value.status, 64),
  };
}

function sanitizeIdentityMemory(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const similarity = finiteOrNull(value.appearance_similarity);
  const cost = finiteOrNull(value.association_cost);
  return {
    hits: nonNegativeIntegerOrNull(value.hits),
    workPrototypeCount: nonNegativeIntegerOrNull(value.work_prototype_count),
    stablePrototypeCount: nonNegativeIntegerOrNull(value.stable_prototype_count),
    appearanceSimilarity: similarity !== null && similarity >= -1 && similarity <= 1
      ? similarity : null,
    associationCost: cost !== null && cost >= 0 ? cost : null,
    associationReason: typeof value.association_reason === 'string'
      ? value.association_reason.slice(0, 128) : null,
  };
}

function sanitizeTarget(target) {
  if (!target || typeof target !== 'object') return null;
  const pose = target.pose && typeof target.pose === 'object' ? target.pose : null;
  const identityStatus = new Set(['tentative', 'confirmed', 'occluded', 'inactive', 'ambiguous'])
    .has(target.identity_status) ? target.identity_status : 'unknown';
  const positionM = finitePosition(pose ? pose.xyz_m : target.position_m);
  const graspPreview = sanitizeGraspPreview(target.grasp_preview);
  const perceptionReasons = boundedStrings(target.reasons);
  const graspReasons = [];
  if (target.actionable !== true) {
    graspReasons.push(...(perceptionReasons.length ? perceptionReasons : ['perception_not_actionable']));
  }
  if (graspPreview === null) graspReasons.push('grasp_preview_unavailable');
  graspReasons.push('physical_grasp_execution_locked');
  let targetState = 'tracked_3d';
  if (identityStatus !== 'confirmed') targetState = 'identity_pending';
  else if (positionM === null) targetState = 'depth_pending';
  else if (target.actionable !== true) targetState = 'blocked';
  else if (graspPreview !== null) targetState = 'grasp_preview';
  return {
    detectionId: nonNegativeIntegerOrNull(target.detection_id),
    identityId: nonNegativeIntegerOrNull(target.identity_id ?? target.id),
    identityStatus,
    identityMemory: sanitizeIdentityMemory(target.identity_memory),
    label: typeof target.label === 'string' ? target.label.slice(0, 128) : 'unknown',
    score: finiteOrNull(target.score ?? target.conf),
    positionM,
    positionFrame: boundedString(pose?.frame, 64),
    positionStdM: positionStandardDeviation(pose?.covariance_m2),
    calibrationIdShort: shortCalibrationId(pose?.calibration_id),
    registeredDepthPoints: nonNegativeIntegerOrNull(target.registered_depth_points) ?? 0,
    targetState,
    graspPointPx: graspPreview?.pointPx ?? null,
    graspPointM: graspPreview?.pointM ?? null,
    graspPointFrame: graspPreview?.frame ?? null,
    graspPointStatus: graspPreview?.status ?? null,
    graspAllowed: false,
    graspReasons: [...new Set(graspReasons)],
    reasons: perceptionReasons,
    actionable: false,
  };
}

function sanitizeActiveView(report) {
  if (!report || typeof report !== 'object') return null;
  const kinds = new Set(['none', 'coarse_pose', 'refine_delta']);
  const centralFraction = finiteOrNull(report.central_fraction);
  return {
    detectionId: nonNegativeIntegerOrNull(report.detection_id),
    identityId: nonNegativeIntegerOrNull(report.identity_id),
    kind: kinds.has(report.kind) ? report.kind : 'none',
    targetPoseId: typeof report.target_pose_id === 'string'
      ? report.target_pose_id.slice(0, 128)
      : null,
    expiresNs: nonNegativeIntegerOrNull(report.expires_ns),
    coarseCenterXYM: finiteXY(report.coarse_center_xy_m),
    validDepthPoints: nonNegativeIntegerOrNull(report.valid_depth_points),
    centralFraction: centralFraction !== null && centralFraction >= 0 && centralFraction <= 1
      ? centralFraction
      : null,
    depthAcceptable: typeof report.depth_acceptable === 'boolean'
      ? report.depth_acceptable
      : null,
    stableSamples: nonNegativeIntegerOrNull(report.stable_samples),
    remainingRefinements: nonNegativeIntegerOrNull(report.remaining_refinements),
    reasons: boundedStrings(report.reasons),
    executionEnabled: false,
  };
}

class VisionStatusStore {
  constructor({ staleAfterMs = 2000, maxTargets = 256 } = {}) {
    if (!Number.isFinite(staleAfterMs) || staleAfterMs <= 0) {
      throw new TypeError('staleAfterMs must be finite and positive');
    }
    if (!Number.isInteger(maxTargets) || maxTargets < 1 || maxTargets > 256) {
      throw new TypeError('maxTargets must be an integer within [1, 256]');
    }
    this.staleAfterMs = staleAfterMs;
    this.maxTargets = maxTargets;
    this.lastEventTs = null;
    this.lastTargetsTs = null;
    this.online = false;
    this.modelReady = false;
    this.d435Ready = false;
    this.roles = {
      canonicalRgb: 'lumos_rgb',
      metricDepth: 'd435_depth',
      debugRgb: 'd435_rgb',
    };
    this.sequences = { lumos: null, d435: null };
    this.metrics = {
      latencyMs: null,
      latencyP95Ms: null,
      gpuMemoryReservedGib: null,
    };
    this.taskCheckpointValidated = false;
    this.blockers = ['vision_not_started'];
    this.targets = [];
    this.activeViewReports = [];
    this.activeViewControl = {
      phase: 'idle',
      sessionId: null,
      identityId: null,
      proposalId: null,
      requestId: null,
      reasons: [],
      evidenceIdsShort: [],
      moveReady: false,
      kind: null,
      targetPoseId: null,
      maxStepM: null,
      requiresConfirmation: true,
    };
    this.error = null;
  }

  _timestamp(event) {
    const timestamp = finiteOrNull(event && event.ts);
    if (timestamp !== null && timestamp >= 0) this.lastEventTs = timestamp;
  }

  updateStatus(event) {
    if (!event || typeof event !== 'object') return;
    this._timestamp(event);
    if (event.type === 'vision_error') {
      this.online = false;
      this.modelReady = false;
      this.error = typeof event.message === 'string' ? event.message.slice(0, 512) : null;
      this.blockers = boundedStrings(event.blockers);
      if (!this.blockers.length) this.blockers = ['vision_unavailable'];
      return;
    }
    if (event.type !== 'vision_status') return;
    this.online = event.online === true;
    this.modelReady = event.model_ready === true;
    this.error = typeof event.model_error === 'string' ? event.model_error.slice(0, 512) : null;
    if (typeof event.canonical_rgb_source === 'string') {
      this.roles.canonicalRgb = event.canonical_rgb_source;
    }
    if (typeof event.metric_depth_source === 'string') {
      this.roles.metricDepth = event.metric_depth_source;
    }
    this.sequences = {
      lumos: nonNegativeIntegerOrNull(event.lumos_sequence),
      d435: nonNegativeIntegerOrNull(event.d435_sequence),
    };
    this.metrics = {
      latencyMs: finiteOrNull(event.latency_ms),
      latencyP95Ms: finiteOrNull(event.latency_p95_ms),
      gpuMemoryReservedGib: finiteOrNull(event.gpu_memory_reserved_gib),
    };
    this.taskCheckpointValidated = event.task_checkpoint_validated === true;
    this.blockers = boundedStrings(event.blockers);
  }

  updateCamera(event) {
    if (!event || typeof event !== 'object') return;
    this._timestamp(event);
    if (event.type === 'camera_status') this.d435Ready = event.d435_ready === true;
    if (event.type === 'camera_error') this.d435Ready = false;
  }

  updateTargets(event) {
    if (!event || typeof event !== 'object' || event.type !== 'detection_result') return;
    this._timestamp(event);
    this.lastTargetsTs = finiteOrNull(event.ts);
    const rawTargets = Array.isArray(event.targets) ? event.targets : [];
    this.targets = rawTargets
      .slice(0, this.maxTargets)
      .map(sanitizeTarget)
      .filter(Boolean);
    const rawActiveView = Array.isArray(event.active_view_reports)
      ? event.active_view_reports
      : [];
    this.activeViewReports = rawActiveView
      .slice(0, this.maxTargets)
      .map(sanitizeActiveView)
      .filter(Boolean);
  }

  trustedTargets(nowMs = Date.now()) {
    const now = finiteOrNull(nowMs);
    if (now === null || this.lastTargetsTs === null || now < this.lastTargetsTs ||
        now - this.lastTargetsTs > this.staleAfterMs) return [];
    return this.targets
      .filter(target => target.identityId !== null && target.identityStatus === 'confirmed')
      .map(target => ({ identityId: target.identityId, label: target.label }));
  }

  updateActiveViewState(event) {
    if (!event || typeof event !== 'object' || event.type !== 'active_view_state') return;
    const phases = new Set([
      'idle', 'target_locked', 'coarse_view_planned', 'move_authorized',
      'moving_to_view', 'settling', 'verifying_identity', 'acquiring_depth',
      'refine_view', 'grasp_preview', 'waiting_operator_confirmation',
      'ready_for_existing_grasp_gate', 'aborted', 'complete',
    ]);
    const evidenceIds = boundedStrings(event.evidence_ids, 32)
      .filter(value => /^sha256:[0-9a-f]{64}$/.test(value));
    const sameProposal = this.activeViewControl.proposalId !== null &&
      this.activeViewControl.proposalId === event.proposal_id;
    this.activeViewControl = {
      ...this.activeViewControl,
      phase: phases.has(event.phase) ? event.phase : 'aborted',
      sessionId: typeof event.session_id === 'string' ? event.session_id : null,
      identityId: nonNegativeIntegerOrNull(event.identity_id),
      proposalId: typeof event.proposal_id === 'string' ? event.proposal_id : null,
      requestId: typeof event.request_id === 'string' ? event.request_id : null,
      reasons: boundedStrings(event.reasons),
      evidenceIdsShort: evidenceIds.map(value => `${value.slice(0, 19)}…`),
      moveReady: sameProposal && this.activeViewControl.moveReady,
      kind: sameProposal ? this.activeViewControl.kind : null,
      targetPoseId: sameProposal ? this.activeViewControl.targetPoseId : null,
      maxStepM: sameProposal ? this.activeViewControl.maxStepM : null,
    };
  }

  updateActiveViewMoveReady(event) {
    if (!event || typeof event !== 'object') return;
    const evidenceIds = boundedStrings(event.evidenceIds, 32)
      .filter(value => /^sha256:[0-9a-f]{64}$/.test(value));
    this.activeViewControl = {
      ...this.activeViewControl,
      sessionId: typeof event.sessionId === 'string' ? event.sessionId : null,
      proposalId: typeof event.proposalId === 'string' ? event.proposalId : null,
      identityId: nonNegativeIntegerOrNull(event.identityId),
      evidenceIdsShort: evidenceIds.map(value => `${value.slice(0, 19)}…`),
      moveReady: true,
      kind: new Set(['coarse_pose', 'refine_delta']).has(event.kind) ? event.kind : null,
      targetPoseId: typeof event.targetPoseId === 'string' ? event.targetPoseId.slice(0, 128) : null,
      maxStepM: finiteOrNull(event.maxStepM),
      requiresConfirmation: event.requiresConfirmation === true,
    };
  }

  snapshot(nowMs = Date.now()) {
    const now = finiteOrNull(nowMs);
    if (now === null) throw new TypeError('snapshot time must be finite');
    const sourceAgeMs = this.lastEventTs === null ? null : Math.max(0, now - this.lastEventTs);
    const stale = sourceAgeMs === null || sourceAgeMs > this.staleAfterMs;
    const blockers = [...this.blockers];
    if (stale) blockers.push('vision_status_stale');
    if (!this.modelReady && !blockers.includes('model_unavailable')) {
      blockers.push('model_unavailable');
    }
    return {
      online: this.online,
      modelReady: this.modelReady,
      d435Ready: this.d435Ready,
      lumosReady: this.sequences.lumos !== null,
      roles: { ...this.roles },
      sequences: { ...this.sequences },
      metrics: { ...this.metrics },
      targets: this.targets.map(target => ({
        ...target,
        positionM: target.positionM === null ? null : [...target.positionM],
        positionStdM: target.positionStdM === null ? null : [...target.positionStdM],
        graspPointPx: target.graspPointPx === null ? null : [...target.graspPointPx],
        graspPointM: target.graspPointM === null ? null : [...target.graspPointM],
        graspReasons: [...target.graspReasons],
        reasons: [...target.reasons],
        identityMemory: target.identityMemory === null ? null : { ...target.identityMemory },
      })),
      activeView: {
        executionEnabled: false,
        control: {
          ...this.activeViewControl,
          reasons: [...this.activeViewControl.reasons],
          evidenceIdsShort: [...this.activeViewControl.evidenceIdsShort],
        },
        reports: this.activeViewReports.map(report => ({
          ...report,
          coarseCenterXYM: report.coarseCenterXYM === null
            ? null
            : [...report.coarseCenterXYM],
          reasons: [...report.reasons],
        })),
      },
      blockers: [...new Set(blockers)],
      sourceAgeMs,
      stale,
      taskCheckpointValidated: this.taskCheckpointValidated,
      robotExecutionEnabled: false,
      error: this.error,
    };
  }
}

module.exports = {
  VisionStatusStore,
  sanitizeActiveView,
  sanitizeIdentityMemory,
  sanitizeGraspPreview,
  sanitizeTarget,
};
