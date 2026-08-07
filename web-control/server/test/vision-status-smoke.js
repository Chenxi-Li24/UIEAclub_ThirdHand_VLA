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
      identity_status: 'confirmed',
      label: 'bottle',
      score: 0.95,
      actionable: true,
      reasons: ['calibration_unavailable'],
      pose: { xyz_m: [Number.NaN, 0.2, 0.3] },
      identity_memory: {
        hits: 5,
        work_prototype_count: 4,
        stable_prototype_count: 3,
        appearance_similarity: 0.93,
        association_cost: 0.07,
        association_reason: null,
        dense_features: [1, 2, 3],
      },
    },
    {
      detection_id: 8,
      identity_id: 4,
      identity_status: 'confirmed',
      label: 'cup',
      score: 0.91,
      actionable: true,
      reasons: [],
      registered_depth_points: 184,
      pose: {
        xyz_m: [0.342, -0.118, 0.041],
        covariance_m2: [
          [0.000004, 0, 0],
          [0, 0.000009, 0],
          [0, 0, 0.000016],
        ],
        frame: 'robot_base',
        calibration_id: `sha256:${'b'.repeat(64)}`,
      },
      grasp_preview: {
        pixel_xy: [63, 44],
        xyz_m: [0.340, -0.116, 0.041],
        frame: 'robot_base',
        status: 'candidate',
      },
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
assert.equal(current.targets[0].identityStatus, 'confirmed');
assert.equal(current.targets[0].positionM, null);
assert.equal(current.targets[0].targetState, 'depth_pending');
assert.equal(current.targets[0].registeredDepthPoints, 0);
assert.equal(current.targets[0].graspAllowed, false);
assert.equal(current.targets[0].graspReasons.includes('grasp_preview_unavailable'), true);
assert.equal(current.targets[0].graspReasons.includes('physical_grasp_execution_locked'), true);
assert.deepEqual(current.targets[0].identityMemory, {
  hits: 5,
  workPrototypeCount: 4,
  stablePrototypeCount: 3,
  appearanceSimilarity: 0.93,
  associationCost: 0.07,
  associationReason: null,
});
assert.deepEqual(current.targets[1], {
  detectionId: 8,
  identityId: 4,
  identityStatus: 'confirmed',
  identityMemory: null,
  label: 'cup',
  score: 0.91,
  positionM: [0.342, -0.118, 0.041],
  positionFrame: 'robot_base',
  positionStdM: [0.002, 0.003, 0.004],
  calibrationIdShort: 'sha256:bbbbbbbbbbbb…',
  registeredDepthPoints: 184,
  targetState: 'grasp_preview',
  graspPointPx: [63, 44],
  graspPointM: [0.34, -0.116, 0.041],
  graspPointFrame: 'robot_base',
  graspPointStatus: 'candidate',
  graspAllowed: false,
  graspReasons: ['physical_grasp_execution_locked'],
  reasons: [],
  actionable: false,
});
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
assert.deepEqual(store.trustedTargets(1500), [
  { identityId: 3, label: 'bottle' },
  { identityId: 4, label: 'cup' },
]);
assert.deepEqual(store.trustedTargets(3102), []);

store.updateActiveViewState({
  type: 'active_view_state',
  phase: 'moving_to_view',
  session_id: '11111111-1111-4111-8111-111111111111',
  identity_id: 3,
  proposal_id: '22222222-2222-4222-8222-222222222222',
  request_id: '33333333-3333-4333-8333-333333333333',
  evidence_ids: [`sha256:${'a'.repeat(64)}`],
  reasons: [],
  joints_deg: [1, 2, 3, 4, 5, 6],
});
store.updateActiveViewMoveReady({
  sessionId: '11111111-1111-4111-8111-111111111111',
  proposalId: '22222222-2222-4222-8222-222222222222',
  identityId: 3,
  kind: 'coarse_pose',
  targetPoseId: 'table_left',
  evidenceIds: [`sha256:${'a'.repeat(64)}`],
  maxStepM: 0.020,
  requiresConfirmation: true,
});
const controlled = store.snapshot(1500);
assert.deepEqual(controlled.activeView.control, {
  phase: 'moving_to_view',
  sessionId: '11111111-1111-4111-8111-111111111111',
  identityId: 3,
  proposalId: '22222222-2222-4222-8222-222222222222',
  requestId: '33333333-3333-4333-8333-333333333333',
  reasons: [],
  evidenceIdsShort: ['sha256:aaaaaaaaaaaa…'],
  moveReady: true,
  kind: 'coarse_pose',
  targetPoseId: 'table_left',
  maxStepM: 0.02,
  requiresConfirmation: true,
});
assert.equal(JSON.stringify(controlled).includes('joints_deg'), false);

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
