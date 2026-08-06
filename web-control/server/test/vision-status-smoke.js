'use strict';

const assert = require('assert/strict');
const { VisionStatusStore } = require('../vision-status');

const store = new VisionStatusStore({ staleAfterMs: 2000, maxTargets: 256 });
store.updateStatus({
  type: 'vision_status',
  ts: 1000,
  online: true,
  model_ready: true,
  d435_ready: true,
  canonical_rgb_source: 'lumos_rgb',
  metric_depth_source: 'd435_depth',
  lumos_sequence: 7,
  d435_sequence: 11,
  latency_ms: 123.5,
  latency_p95_ms: 155.0,
  gpu_memory_reserved_gib: 4.25,
  blockers: ['calibration_unavailable'],
  robot_execution_enabled: true,
});
store.updateTargets({
  type: 'detection_result',
  ts: 1001,
  targets: [
    {
      identity_id: 3,
      label: 'bottle',
      score: 0.95,
      actionable: true,
      reasons: ['calibration_unavailable'],
      pose: { xyz_m: [Number.NaN, 0.2, 0.3] },
    },
  ],
  active_view_reports: [
    {
      detection_id: 7,
      identity_id: 3,
      kind: 'coarse_pose',
      target_pose_id: 'table_left',
      expires_ns: 200000000,
      coarse_center_xy_m: [0.2, -0.1],
      valid_depth_points: 75,
      central_fraction: 0.55,
      depth_acceptable: false,
      stable_samples: 2,
      remaining_refinements: 3,
      reasons: ['insufficient_central_coverage'],
      active_view_execution_enabled: true,
      joints_deg: [1, 2, 3, 4, 5, 6],
      delta_base_m: [0.01, 0, 0],
      covariance_xy_m2: [[1, 0], [0, 1]],
      unknown: 'drop me',
    },
  ],
});

const current = store.snapshot(1500);
assert.equal(current.online, true);
assert.equal(current.modelReady, true);
assert.equal(current.stale, false);
assert.equal(current.robotExecutionEnabled, false);
assert.deepEqual(current.roles, {
  canonicalRgb: 'lumos_rgb',
  metricDepth: 'd435_depth',
  debugRgb: 'd435_rgb',
});
assert.deepEqual(current.sequences, { lumos: 7, d435: 11 });
assert.deepEqual(current.metrics, {
  latencyMs: 123.5,
  latencyP95Ms: 155,
  gpuMemoryReservedGib: 4.25,
});
assert.equal(current.targets[0].actionable, false);
assert.equal(current.targets[0].positionM, null);
assert.deepEqual(current.blockers, ['calibration_unavailable']);
assert.equal(current.activeView.executionEnabled, false);
assert.deepEqual(current.activeView.reports[0], {
  detectionId: 7,
  identityId: 3,
  kind: 'coarse_pose',
  targetPoseId: 'table_left',
  expiresNs: 200000000,
  coarseCenterXYM: [0.2, -0.1],
  validDepthPoints: 75,
  centralFraction: 0.55,
  depthAcceptable: false,
  stableSamples: 2,
  remainingRefinements: 3,
  reasons: ['insufficient_central_coverage'],
  executionEnabled: false,
});
assert.equal('jointsDeg' in current.activeView.reports[0], false);
assert.equal('deltaBaseM' in current.activeView.reports[0], false);

const stale = store.snapshot(3102);
assert.equal(stale.stale, true);
assert.equal(stale.sourceAgeMs, 2101);
assert.equal(stale.blockers.includes('vision_status_stale'), true);

const manyTargets = Array.from({ length: 300 }, (_, index) => ({
  identity_id: index,
  label: 'object',
  score: 0.8,
  actionable: false,
  reasons: [],
  pose: { xyz_m: [0.1, 0.2, 0.3] },
}));
store.updateTargets({ type: 'detection_result', ts: 3200, targets: manyTargets });
assert.equal(store.snapshot(3200).targets.length, 256);
store.updateTargets({
  type: 'detection_result',
  ts: 3201,
  active_view_reports: Array.from({ length: 300 }, (_, identity_id) => ({ identity_id })),
});
assert.equal(store.snapshot(3201).activeView.reports.length, 256);

store.updateStatus({
  type: 'vision_error',
  ts: 3300,
  message: 'synthetic failure',
  blockers: ['model_unavailable'],
  robot_execution_enabled: true,
});
const failed = store.snapshot(3300);
assert.equal(failed.online, false);
assert.equal(failed.modelReady, false);
assert.equal(failed.robotExecutionEnabled, false);
assert.equal(failed.blockers.includes('model_unavailable'), true);

console.log('PASS vision status is bounded, finite, stale-aware, and execution-locked');
