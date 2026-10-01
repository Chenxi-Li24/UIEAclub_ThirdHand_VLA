'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { createSupervisedPreview, matchesPreview } = require('../../../src/thirdhand_va/action/operator/supervised_preview');

const target = {
  stableId: 1,
  trackState: 'confirmed',
  depthValid: true,
  evidenceId: `sha256:${'a'.repeat(64)}`,
  motionEpoch: 0,
  frameId: 12,
  graspPreview: {
    preview_id: `sha256:${'b'.repeat(64)}`,
    camera_xyz_m: [0.1, 0.2, 0.3],
    surface_xyz_m: [0.3, 0.1, 0.2],
    grip_target_xyz_m: [0.3, 0.1, 0.2],
    blockers: ['target_geometry_unavailable'],
  },
};
const robotState = {
  poseFrame: 'robot_flange', connected: true, healthy: true,
  stateFresh: true, stationary: true, stateSequence: 7,
};
const runtimeEvidence = { calibration_id: null, vision_config_id: `sha256:${'c'.repeat(64)}` };

test('supervised preview still blocks missing geometry and disabled execution', () => {
  const preview = createSupervisedPreview({
    target, robotState, runtimeEvidence,
    config: { execution_enabled: false, grasp: { grip_transform: { validated: false } } },
    nowMs: 1000,
  });
  assert.equal(preview.executable, false);
  assert.equal(preview.plan, null);
  assert.deepEqual(preview.coordinates.grip_target_xyz_m, [0.3, 0.1, 0.2]);
  assert.ok(preview.blockers.includes('execution_disabled'));
  assert.ok(preview.blockers.includes('target_geometry_unavailable'));
  assert.equal(preview.blockers.includes('calibration_not_approved'), false);
  assert.equal(preview.blockers.includes('grip_transform_unverified'), false);
});

test('approval flags alone do not block a preview with real coordinates and plan', () => {
  const preview = createSupervisedPreview({
    target: { ...target, actionEvidence: { id: 'test-evidence' },
      graspPreview: { ...target.graspPreview, blockers: [] } },
    robotState, runtimeEvidence,
    config: { execution_enabled: true, grasp: { grip_transform: { validated: false } } },
    nowMs: 1000,
    buildPlan: () => ({ schema: 'thirdhand-execution-plan-v2' }),
  });
  assert.equal(preview.executable, true);
  assert.deepEqual(preview.blockers, []);
});

test('lift-only preview needs base coordinates but not alignment approval evidence', () => {
  const preview = createSupervisedPreview({
    target: { ...target, baseXyzM: [0.30, 0.10, 0.20],
      positionStdM: [0.002, 0.002, 0.003],
      graspPreview: { ...target.graspPreview, blockers: [] } },
    robotState: { ...robotState, stationary: false, moving: false }, runtimeEvidence,
    config: { execution_enabled: true, workflow_mode: 'lift_only', grasp: {} },
    nowMs: 1000,
    buildPlan: () => ({ schema: 'thirdhand-execution-plan-v2', mode: 'lift_only' }),
  });
  assert.equal(preview.executable, true);
  assert.deepEqual(preview.blockers, []);
});

test('a single visual target cannot impersonate alignment handoff evidence', () => {
  const preview = createSupervisedPreview({
    target: { ...target, graspPreview: { ...target.graspPreview, blockers: [] } },
    robotState, runtimeEvidence,
    config: { execution_enabled: true, grasp: {} }, nowMs: 1000,
    buildPlan: () => ({ schema: 'thirdhand-execution-plan-v2' }),
  });
  assert.equal(preview.executable, false);
  assert.ok(preview.blockers.includes('alignment_handoff_evidence_unavailable'));
});

test('preview binding rejects changed frame, motion epoch, robot state, or runtime', () => {
  const preview = createSupervisedPreview({
    target, robotState, runtimeEvidence,
    config: { execution_enabled: false, grasp: { grip_transform: { validated: false } } },
    nowMs: 1000,
  });
  assert.equal(matchesPreview(preview, preview.evidence, 1200), true);
  assert.equal(matchesPreview(preview, { ...preview.evidence, frameId: 13 }, 1200), false);
  assert.equal(matchesPreview(preview, { ...preview.evidence, motionEpoch: 1 }, 1200), false);
  assert.equal(matchesPreview(preview, { ...preview.evidence, robotStateSequence: 8 }, 1200), false);
  assert.equal(matchesPreview(preview, { ...preview.evidence, visionConfigId: `sha256:${'d'.repeat(64)}` }, 1200), false);
  assert.equal(matchesPreview(preview, preview.evidence, 5000), false);
});
