'use strict';

function finiteOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nonNegativeIntegerOrNull(value) {
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

function sanitizeTarget(target) {
  if (!target || typeof target !== 'object') return null;
  const pose = target.pose && typeof target.pose === 'object' ? target.pose : null;
  return {
    identityId: nonNegativeIntegerOrNull(target.identity_id ?? target.id),
    label: typeof target.label === 'string' ? target.label.slice(0, 128) : 'unknown',
    score: finiteOrNull(target.score ?? target.conf),
    positionM: finitePosition(pose ? pose.xyz_m : target.position_m),
    reasons: boundedStrings(target.reasons),
    actionable: false,
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
    const rawTargets = Array.isArray(event.targets) ? event.targets : [];
    this.targets = rawTargets
      .slice(0, this.maxTargets)
      .map(sanitizeTarget)
      .filter(Boolean);
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
      targets: this.targets.map(target => ({ ...target })),
      blockers: [...new Set(blockers)],
      sourceAgeMs,
      stale,
      taskCheckpointValidated: this.taskCheckpointValidated,
      robotExecutionEnabled: false,
      error: this.error,
    };
  }
}

module.exports = { VisionStatusStore, sanitizeTarget };
