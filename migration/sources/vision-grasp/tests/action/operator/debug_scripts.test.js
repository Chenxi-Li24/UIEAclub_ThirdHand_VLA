'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '../../..');
const { waitForFreshHomeState } = require(
  '../../../scripts/action/validate_handeye_pregrasp'
);
const { isRetryableValidationReason } = require(
  '../../../scripts/action/validate_handeye_pregrasp'
);
const { createStartupHomeCoordinator, waitForHomeCoordinator } = require(
  '../../../scripts/action/validate_handeye_pregrasp'
);
const { buildClearanceObservationReport } = require(
  '../../../scripts/action/validate_handeye_pregrasp'
);

function run(script, args = []) {
  return spawnSync(process.execPath, [path.join(root, script), ...args], {
    cwd: root,
    encoding: 'utf8',
  });
}

test('alignment debug is a disabled simulation and sends no robot command', () => {
  const result = run('scripts/action/debug_alignment.js');
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.result.reason, 'visual_align_disabled');
  assert.equal(payload.sent_commands, 0);
  assert.equal(payload.robot_control_enabled, false);
});

test('alignment fixture shows reobservation phases with memory-only adapters', () => {
  const result = run('scripts/action/debug_alignment.js', [
    '--target-id', '2', '--fixture', 'tests/fixtures/action/alignment.json',
  ]);
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.deepEqual(payload.phases, [
    'MOVING_TO_PREGRASP', 'SETTLING', 'REOBSERVING', 'HANDED_OFF',
  ]);
  assert.equal(payload.selections[0].stable_id, 2);
  assert.equal(payload.pose_resets[0].motion_epoch, 1);
  assert.equal(payload.robot_control_enabled, false);
});

test('grasp debug stays blocked unless every explicit gate is supplied', () => {
  const result = run('scripts/action/debug_grasp.js');
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.result.accepted, false);
  assert.equal(payload.result.reason, 'execution_disabled');
  assert.equal(payload.sent_commands, 0);
  assert.equal(payload.robot_control_enabled, false);
});

test('approved grasp fixture simulates all nine commands without hardware', () => {
  const result = run('scripts/action/debug_grasp.js', [
    '--fixture', 'tests/fixtures/action/approved-plan.json',
  ]);
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.deepEqual(payload.command_sources, [
    'grasp:open', 'grasp:final_approach', 'grasp:close', 'grasp:lift',
    'grasp:transfer', 'grasp:lower', 'grasp:release', 'grasp:retreat',
    'grasp:return_home',
  ]);
  assert.equal(payload.final.phase, 'complete');
  assert.equal(payload.robot_control_enabled, false);
});

test('Home gate debugger reports measured joint error without hardware', () => {
  const result = run('scripts/action/debug_home.js', [
    '--home', '0,15,-30,5,0,0',
    '--actual', '0.2,14.7,-29.6,4.8,0.1,-0.2',
    '--tolerance', '0.5',
  ]);
  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.allowed, true);
  assert.equal(payload.max_joint_error_deg, 0.4);
  assert.deepEqual(payload.blockers, []);
  assert.equal(payload.hardware_connected, false);
  assert.equal(payload.robot_control_enabled, false);
});

test('clearance plan debugger runs the real planner without camera or robot hardware', () => {
  const result = run('scripts/action/debug_pregrasp_validation.js', [
    '--fixture', 'tests/fixtures/action/handeye-clearance.json',
  ]);

  assert.equal(result.status, 0, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.result.approved, true);
  assert.deepEqual(payload.result.stages.map(stage => stage.phase), [
    'safe_height', 'over_target_clearance',
  ]);
  assert.equal(payload.result.commandsDescent, false);
  assert.equal(payload.result.commandsGripper, false);
  assert.equal(payload.hardware_connected, false);
  assert.equal(payload.camera_connected, false);
  assert.equal(payload.robot_control_enabled, false);
});

test('hand-eye commissioning waits for a new stationary Home state after return', async () => {
  const home = [-0.163927, -2.611904, -0.579209, 33.058620, 0.338783, 0.185784];
  const base = {
    connected: true, healthy: true, stateFresh: true,
    jointsDeg: home, velocitiesDegS: [0, 0, 0, 0, 0, 0],
  };
  const states = [
    { ...base, stateSequence: 10, moving: false, stationary: true },
    { ...base, stateSequence: 11, moving: true, stationary: false },
    { ...base, stateSequence: 12, moving: false, stationary: true },
  ];
  let index = 0;
  const robotClient = {
    getRobotState() {
      const state = states[Math.min(index, states.length - 1)];
      index += 1;
      return state;
    },
  };

  const result = await waitForFreshHomeState({
    robotClient,
    boundaryStateSequence: 10,
    homeJointsDeg: home,
    toleranceDeg: 0.5,
    timeoutMs: 500,
  });

  assert.equal(result.state.stateSequence, 12);
  assert.equal(result.home.allowed, true);
});

test('hand-eye commissioning waits through transient state but not hard blockers', () => {
  assert.equal(isRetryableValidationReason('robot_not_stationary'), true);
  assert.equal(isRetryableValidationReason('validation_target_stale'), true);
  assert.equal(isRetryableValidationReason('validation_target_invalid'), true);
  assert.equal(isRetryableValidationReason('validation_preview_pending'), true);
  assert.equal(isRetryableValidationReason('unexpected_validation_blockers'), false);
  assert.equal(isRetryableValidationReason('validation_workspace_rejected'), false);
});

test('clearance observation report cannot be used as a hand-eye approval report', () => {
  const report = buildClearanceObservationReport({
    targetId: 1,
    plan: {
      calibrationId: `sha256:${'a'.repeat(64)}`,
      previewId: `sha256:${'b'.repeat(64)}`,
      detectedGraspM: [0.40, 0.05, 0.08],
      observationM: [0.40, 0.05, 0.306],
      stages: [
        { phase: 'safe_height', position: [0.25, 0, 0.306], euler: [0, 0.52, 0] },
        { phase: 'over_target_clearance', position: [0.40, 0.05, 0.306],
          euler: [0, 0.52, 0] },
      ],
      commandsGripper: false,
      commandsDescent: false,
    },
    overlayFile: null,
    createdAt: '2026-08-24T00:00:00.000Z',
  });

  assert.equal(report.schema, 'thirdhand-handeye-clearance-observation-v1');
  assert.equal(report.eligible_for_handeye_approval, false);
  assert.equal(report.grasp_offset_applied, false);
  assert.equal(report.orientation_changed, false);
  assert.equal(report.commands_descent, false);
  assert.equal(report.gripper_commanded, false);
  assert.equal(report.software_cleanup_acknowledged, true);
  assert.equal(report.depower_independently_confirmed, false);
});

test('hand-eye commissioning fails before hardware when camera authorization is missing', () => {
  const result = run('scripts/action/validate_handeye_pregrasp.js', [
    '--target-id', '1', '--allow-robot',
  ]);

  assert.equal(result.status, 2, result.stderr);
  const payload = JSON.parse(result.stdout);
  assert.equal(payload.status, 'blocked');
  assert.equal(payload.reasons.includes('camera_access_ack_missing'), true);
});

test('hand-eye commissioning wires the same approved Home coordinator as web service', () => {
  const robotClient = { name: 'robot-client' };
  const config = {
    home_timeout_ms: 45000,
    robot: {
      home_tolerance_deg: 0.5,
      presets: { home: [0, 15, -30, 5, 0, 0] },
    },
    place: {
      home_preset: 'home',
      startup_home_validated: true,
      startup_joint_ranges_deg: [
        [-5, 5], [10, 20], [-35, -25], [0, 10], [-5, 5], [-5, 5],
      ],
    },
  };
  let received = null;
  class FakeHomeCoordinator {
    constructor(options) { received = options; }
  }

  const coordinator = createStartupHomeCoordinator({
    robotClient, config, HomeCoordinatorClass: FakeHomeCoordinator,
  });

  assert.equal(coordinator instanceof FakeHomeCoordinator, true);
  assert.equal(received.robotClient, robotClient);
  assert.equal(received.homePreset, 'home');
  assert.deepEqual(received.homeJointsDeg, [0, 15, -30, 5, 0, 0]);
  assert.equal(received.toleranceDeg, 0.5);
  assert.equal(received.startupValidated, true);
  assert.deepEqual(received.startupJointRangesDeg, config.place.startup_joint_ranges_deg);
  assert.equal(received.timeoutMs, 45000);
});

test('hand-eye commissioning waits until Home ready and surfaces a failed Home reason', async () => {
  const ready = {
    snapshotCalls: 0,
    start() { return { accepted: true, phase: 'waiting_robot' }; },
    snapshot() {
      this.snapshotCalls += 1;
      return this.snapshotCalls < 2
        ? { phase: 'homing', ready: false, reason: null }
        : { phase: 'ready', ready: true, reason: null };
    },
  };
  const result = await waitForHomeCoordinator(ready, 500);
  assert.equal(result.ready, true);

  const failed = {
    start() { return { accepted: true, phase: 'waiting_robot' }; },
    snapshot() { return { phase: 'failed', ready: false, reason: 'home_not_verified' }; },
  };
  await assert.rejects(
    () => waitForHomeCoordinator(failed, 500),
    /home_not_verified/
  );
});
