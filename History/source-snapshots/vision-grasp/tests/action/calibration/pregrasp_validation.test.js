'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { authorizePregraspValidation } = require(
  '../../../src/thirdhand_va/action/calibration/pregrasp_validation'
);

function fixture(overrides = {}) {
  return {
    targetId: 1,
    nowMs: 1100,
    target: {
      stable_id: 1,
      selected: true,
      track_state: 'confirmed',
      depth_valid: true,
      blockers: [],
      observed_at_ms: 1000,
      grasp_preview: {
        frame: 'robot_base',
        calibration_id: `sha256:${'a'.repeat(64)}`,
        preview_id: `sha256:${'b'.repeat(64)}`,
        grasp_xyz_m: [0.40, 0.05, 0.08],
        stable_samples: 5,
        width_m: 0.06,
        allowed: false,
        blockers: [
          'handeye_physical_validation_pending',
          'handeye_activation_locked',
        ],
      },
    },
    robot: {
      connected: true,
      healthy: true,
      moving: false,
      stationary: true,
      stateFresh: true,
      poseFrame: 'robot_flange',
      flangePositionM: [0.255, 0, 0.04],
      flangeEulerRad: [0, 0.52, 0],
      jointsDeg: [-0.16, -2.61, -0.58, 33.06, 0.34, 0.19],
      gripperWidthM: 0.08,
    },
    config: {
      robot: {
        home_tolerance_deg: 0.5,
        presets: {
          home: [-0.16, -2.61, -0.58, 33.06, 0.34, 0.19],
        },
      },
      workspace_m: { x: [0.15, 0.66], y: [-0.65, 0.45], z: [0.04, 0.65] },
      motion: {
        pregrasp_offset_m: 0.10,
        safe_transit_z_m: 0.306371896,
        linear_speed_m_s: 0.03,
        grasp_euler_rad: [0.052626251, -0.083733625, 0.492493650],
      },
      grasp: {
        flange_offset_base_m: [0.0475, 0.01, 0],
        offset_validated: false,
      },
      place: { home_preset: 'home' },
    },
    ...overrides,
  };
}

test('pending hand-eye preview authorizes only a clearance plan without offset rotation or descent', () => {
  const result = authorizePregraspValidation(fixture());

  assert.equal(result.approved, true);
  assert.deepEqual(result.detectedGraspM, [0.40, 0.05, 0.08]);
  assert.deepEqual(result.observationM, [0.40, 0.05, 0.306371896]);
  assert.deepEqual(result.stages.map(stage => stage.phase), [
    'safe_height', 'over_target_clearance',
  ]);
  assert.deepEqual(result.stages.map(stage => stage.position), [
    [0.255, 0, 0.306371896],
    [0.40, 0.05, 0.306371896],
  ]);
  assert.deepEqual(result.stages.map(stage => stage.euler), [
    [0, 0.52, 0], [0, 0.52, 0],
  ]);
  assert.equal(result.commandsGripper, false);
  assert.equal(result.commandsDescent, false);
  assert.equal('commandedFlangeGraspM' in result, false);
  assert.equal('hoverM' in result, false);
  assert.equal(Object.isFrozen(result), true);
});

test('commissioning plan requires a fresh measured Home proof immediately before motion', () => {
  const away = fixture();
  away.robot.jointsDeg = [2, -2.61, -0.58, 33.06, 0.34, 0.19];
  assert.deepEqual(authorizePregraspValidation(away), {
    approved: false, reason: 'robot_not_at_home',
  });

  const missing = fixture();
  delete missing.robot.jointsDeg;
  assert.deepEqual(authorizePregraspValidation(missing), {
    approved: false, reason: 'robot_joint_state_invalid',
  });
});

test('approved preview and extra blockers cannot enter commissioning bypass', () => {
  const approved = fixture();
  approved.target.grasp_preview.allowed = true;
  approved.target.grasp_preview.blockers = [];
  assert.deepEqual(authorizePregraspValidation(approved), {
    approved: false, reason: 'unexpected_validation_blockers',
  });

  const extra = fixture();
  extra.target.grasp_preview.blockers.push('approach_corridor_axis_mismatch');
  assert.deepEqual(authorizePregraspValidation(extra), {
    approved: false, reason: 'unexpected_validation_blockers',
  });
});

test('incomplete visual stability and stationary settling remain retryable', () => {
  const pending = fixture();
  pending.target.grasp_preview.stable_samples = 0;
  pending.target.grasp_preview.blockers.push(
    'vision_not_ready', 'arm_not_stationary', 'frame_precedes_stationary_settle'
  );

  assert.deepEqual(authorizePregraspValidation(pending), {
    approved: false, reason: 'validation_preview_pending',
  });
});

test('stale target and insufficient safe-height clearance are rejected', () => {
  assert.deepEqual(authorizePregraspValidation(fixture({ nowMs: 1601 })), {
    approved: false, reason: 'validation_target_stale',
  });

  const unsafe = fixture();
  unsafe.config.motion.safe_transit_z_m = 0.20;
  assert.deepEqual(authorizePregraspValidation(unsafe), {
    approved: false, reason: 'safe_transit_clearance_insufficient',
  });
});
