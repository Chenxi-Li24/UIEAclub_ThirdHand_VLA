'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { VisualAlignController } = require(
  '../../../src/thirdhand_va/action/alignment/visual_align_controller'
);

let sequence = 0;
const idFactory = () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}`;

function makeHarness(options = {}) {
  let now = 1000;
  const robot = {
    connected: true, healthy: true, moving: false, stateFresh: true, stationary: true,
    poseFrame: 'robot_flange',
    flangePositionM: [0.30, 0, 0.18], gripperWidthM: 0.080,
  };
  const selections = [];
  const resets = [];
  const commands = [];
  const grasps = [];
  const statuses = [];
  const controller = new VisualAlignController({
    executionEnabled: true,
    getRobotState: () => ({
      ...robot, flangePositionM: [...robot.flangePositionM],
    }),
    selectBottle: command => { selections.push(command); return true; },
    resetTargetPoseReference: command => { resets.push(command); return true; },
    sendRobot: command => { commands.push(command); return true; },
    startGrasp: handoff => { grasps.push(handoff); return { accepted: true }; },
    onStatus: status => statuses.push(status),
    nowMs: () => now,
    idFactory,
    stableWindow: 3,
    graspOffsetBaseM: [0.0475, 0.01, 0],
    ...(Object.hasOwn(options, 'safeTransitZM')
      ? { safeTransitZM: options.safeTransitZM } : {}),
  });
  function target(overrides = {}) {
    now += 10;
    const epoch = controller.session?.motionEpoch ?? 0;
    const evidenceId = `sha256:${String(now).padStart(64, '0')}`;
    const visionConfigId = `sha256:${'b'.repeat(64)}`;
    const modelProvenance = {
      vision_config_id: visionConfigId,
      camera_registration_id: 'debug-registration',
      camera_mount_id: 'debug-wrist-mount',
      grounding_model: 'debug/grounding',
      grounding_revision: '1'.repeat(40),
      grounding_weights_sha256: `sha256:${'c'.repeat(64)}`,
      sam_model: 'debug/sam',
      sam_revision: '2'.repeat(40),
      sam_weights_sha256: `sha256:${'d'.repeat(64)}`,
    };
    return {
      stableId: 2,
      requestId: 'req-2',
      calibrationId: `sha256:${'c'.repeat(64)}`,
      trackState: 'confirmed',
      motionEpoch: epoch,
      depthValid: true,
      actionable: true,
      calibrationValidated: true,
      safetyApproved: true,
      gripperReady: true,
      blockers: [],
      armStationary: true,
      observedAtMs: now,
      evidenceId,
      visionConfigId,
      modelProvenance,
      posePositionStdM: [0.001, 0.001, 0.002],
      preview: {
        previewId: `sha256:${String(now + 1).padStart(64, '0')}`,
        armStateId: `sha256:${String(now + 2).padStart(64, '0')}`,
        visionEvidenceId: evidenceId,
        visionConfigId,
        modelProvenance,
        pointM: [0.40, 0.05, 0.18],
        stableSamples: 3,
        widthM: 0.06,
        approachBase: [1, 0, 0],
        allowed: true,
      },
      ...overrides,
    };
  }
  function feedStable(overrides = {}) {
    let result;
    for (let index = 0; index < 3; index += 1) {
      result = controller.onVisionTargets([target(overrides)]);
    }
    return result;
  }
  return { controller, robot, selections, resets, commands, grasps, statuses,
    target, feedStable };
}

test('validated safe transit raises, translates, then descends before refinement', () => {
  const h = makeHarness({ safeTransitZM: 0.306371896 });
  h.controller.start({ targetId: 2, requestId: 'req-2' });

  let result = h.feedStable();
  assert.equal(result.phase, 'moving_to_safe_height');
  assert.deepEqual(h.commands[0].position, [0.30, 0, 0.306371896]);

  for (const expected of [
    {
      phase: 'moving_over_pregrasp',
      position: [0.3475, 0.06, 0.306371896],
    },
    {
      phase: 'moving_to_pregrasp',
      position: [0.3475, 0.06, 0.18],
    },
  ]) {
    const command = h.commands.at(-1);
    h.robot.flangePositionM = [...command.position];
    result = h.controller.onRobotEvent({
      type: 'command_complete', request_id: command.request_id, reached: true,
    });
    assert.equal(result.phase, 'settling');
    result = h.feedStable();
    assert.equal(result.phase, expected.phase);
    assert.deepEqual(h.commands.at(-1).position, expected.position);
  }

  const pregrasp = h.commands.at(-1);
  h.robot.flangePositionM = [...pregrasp.position];
  result = h.controller.onRobotEvent({
    type: 'command_complete', request_id: pregrasp.request_id, reached: true,
  });
  assert.equal(result.phase, 'settling');
  result = h.feedStable();
  assert.equal(result.phase, 'handed_off');
  assert.equal(h.grasps.length, 1);
  assert.deepEqual(h.resets.map(item => item.motion_epoch), [1, 2, 3]);
});

test('stable ID pregrasp requires fresh same-epoch depth before handoff', () => {
  const h = makeHarness();

  const started = h.controller.start({ targetId: 2, requestId: 'req-2' });
  assert.equal(started.accepted, true);
  assert.deepEqual(h.selections, [{
    type: 'select_bottle', stable_id: 2, request_id: 'req-2',
  }]);

  let result = h.feedStable();
  assert.equal(result.phase, 'moving_to_pregrasp');
  assert.ok(Math.hypot(...h.commands[0].position.map(
    (value, index) => value - h.robot.flangePositionM[index]
  )) <= 0.40);
  h.robot.flangePositionM = [...h.commands[0].position];
  result = h.controller.onRobotEvent({
    type: 'command_complete', request_id: h.commands[0].request_id, reached: true,
  });
  assert.equal(result.phase, 'settling');
  assert.deepEqual(h.resets, [{
    type: 'reset_target_pose_reference', request_id: 'req-2', motion_epoch: 1,
  }]);

  const missingDepth = h.target({ depthValid: false, preview: null });
  result = h.controller.onVisionTargets([missingDepth]);
  assert.equal(result.reason, 'target_preview_not_approved');
  assert.equal(h.grasps.length, 0);

  result = h.feedStable();
  assert.equal(result.phase, 'handed_off');
  assert.equal(h.grasps.length, 1);
  assert.equal(h.grasps[0].stableId, 2);
  assert.equal(h.grasps[0].motionEpoch, 1);
  assert.equal(h.grasps[0].requestId, 'req-2');
  assert.deepEqual(h.grasps[0].detectedGraspPointM, [0.40, 0.05, 0.18]);
  assert.deepEqual(h.grasps[0].commandedFlangeGraspM, [0.4475, 0.06, 0.18]);
  assert.deepEqual(h.grasps[0].flangeOffsetBaseM, [0.0475, 0.01, 0]);
  assert.equal(Object.hasOwn(h.grasps[0], 'graspPointM'), false);
  assert.ok(h.statuses.some(status => status.phase === 'reobserving'));
});

test('stable target never rebinds to another visible bottle', () => {
  const h = makeHarness();
  h.controller.start({ targetId: 2, requestId: 'req-2' });

  const result = h.controller.onVisionTargets([h.target({ stableId: 3 })]);

  assert.equal(result.accepted, false);
  assert.equal(result.reason, 'target_identity_conflict');
  assert.equal(h.commands.length, 0);
});

test('unhealthy robot is rejected again at alignment start', () => {
  const h = makeHarness();
  h.robot.healthy = false;

  const result = h.controller.start({ targetId: 2, requestId: 'req-2' });

  assert.deepEqual(result, { accepted: false, reason: 'robot_not_healthy' });
  assert.equal(h.selections.length, 0);
  assert.equal(h.commands.length, 0);
});

test('alignment rejects robot state without explicit flange semantics', () => {
  const h = makeHarness();
  delete h.robot.poseFrame;

  const result = h.controller.start({ targetId: 2, requestId: 'req-2' });

  assert.deepEqual(result, { accepted: false, reason: 'robot_pose_frame_invalid' });
});

test('alignment never moves toward calibration-blocked target', () => {
  const h = makeHarness();
  assert.equal(h.controller.start({ targetId: 2, requestId: 'req-2' }).accepted, true);

  const result = h.feedStable({
    actionable: false,
    calibrationValidated: false,
    safetyApproved: false,
    blockers: ['handeye_physical_validation_pending'],
  });

  assert.equal(result.accepted, false);
  assert.equal(result.reason, 'target_not_actionable');
  assert.equal(h.commands.length, 0);
  assert.equal(h.grasps.length, 0);
});

test('alignment cannot advance when completion omits reached true', () => {
  const h = makeHarness();
  h.controller.start({ targetId: 2, requestId: 'req-2' });
  h.feedStable();

  const result = h.controller.onRobotEvent({
    type: 'command_complete', request_id: h.commands[0].request_id,
  });

  assert.equal(result.accepted, false);
  assert.equal(result.reason, 'visual_align_move_failed');
  assert.equal(h.resets.length, 0);
});
