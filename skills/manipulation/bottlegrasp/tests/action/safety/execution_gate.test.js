'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { evaluateExecutionGate } = require(
  '../../../src/thirdhand_va/action/safety/execution_gate'
);
const { checkWorkspace } = require(
  '../../../src/thirdhand_va/action/safety/workspace_check'
);

function validContext(overrides = {}) {
  return {
    executionEnabled: true,
    visionReady: true,
    requestedStableId: 2,
    targetStableId: 2,
    trackState: 'confirmed',
    evidenceId: `sha256:${'a'.repeat(64)}`,
    evidenceAgeMs: 80,
    maxEvidenceAgeMs: 500,
    evidenceMotionEpoch: 3,
    motionEpoch: 3,
    depthValid: true,
    posePositionStdM: [0.001, 0.001, 0.002],
    maxPositionStdM: 0.01,
    calibrationValidated: true,
    armStationary: true,
    safetyApproved: true,
    gripperReady: true,
    placeValidated: true,
    graspOffsetValidated: true,
    widthM: 0.06,
    maxWidthM: 0.072,
    pregraspM: [0.3, 0, 0.2],
    commandedFlangeGraspM: [0.4, 0, 0.2],
    liftM: [0.4, 0, 0.32],
    prePlaceM: [0.2678, 0.0107, 0.28],
    placeM: [0.2678, 0.0107, 0.18],
    retreatM: [0.2678, 0.0107, 0.28],
    ...overrides,
  };
}

test('workspace check names the violated axis and rejects malformed points', () => {
  assert.deepEqual(checkWorkspace([0.4, 0, 0.2]), {
    allowed: true, blockers: [],
  });
  assert.deepEqual(checkWorkspace([0.8, 0, 0.2]), {
    allowed: false, blockers: ['workspace_x_out_of_bounds'],
  });
  assert.deepEqual(checkWorkspace([0.4, Number.NaN, 0.2]), {
    allowed: false, blockers: ['workspace_point_invalid'],
  });
});

test('gate checks the offset approval and every derived waypoint', () => {
  const decision = evaluateExecutionGate(validContext({
    graspOffsetValidated: false,
    pregraspM: [0.8, 0, 0.2],
    liftM: [0.4, 0, 0.8],
    retreatM: [0.2678, -0.8, 0.28],
  }));

  assert.deepEqual(decision.blockers, [
    'grasp_offset_not_validated',
    'pregrasp_workspace_x_out_of_bounds',
    'lift_workspace_z_out_of_bounds',
    'retreat_workspace_y_out_of_bounds',
  ]);
});

test('inactive real config blocks place while a validated fixture can pass', () => {
  const blocked = evaluateExecutionGate(validContext({ placeValidated: false }));
  assert.deepEqual(blocked.blockers, ['place_not_validated']);

  const approved = evaluateExecutionGate(validContext());
  assert.equal(approved.allowed, true);
  assert.equal(approved.robot_control_enabled, true);
  assert.equal(Object.isFrozen(approved), true);
});

test('gate reports identity evidence width and path blockers in fixed order', () => {
  const decision = evaluateExecutionGate(validContext({
    targetStableId: 3,
    evidenceAgeMs: 900,
    evidenceMotionEpoch: 2,
    posePositionStdM: [0.001, 0.014, 0.002],
    widthM: 0.073,
    prePlaceM: [0.8, 0, 0.2],
  }));

  assert.deepEqual(decision.blockers, [
    'target_identity_conflict',
    'evidence_stale',
    'motion_epoch_mismatch',
    'pose_spread_exceeded',
    'grasp_width_exceeded',
    'pre_place_workspace_x_out_of_bounds',
  ]);
  assert.equal(decision.robot_control_enabled, false);
});
