#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const {
  VisualAlignController,
} = require('../../src/thirdhand_va/action/alignment/visual_align_controller');

function parseArgs(argv) {
  const result = { targetId: null, fixture: null };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--target-id') result.targetId = Number(argv[++index]);
    else if (argv[index] === '--fixture') result.fixture = argv[++index];
    else throw new TypeError(`unknown argument: ${argv[index]}`);
  }
  return result;
}

function disabledSmoke() {
  const commands = [];
  const controller = new VisualAlignController({
    executionEnabled: false,
    getRobotState: () => ({
      connected: true, healthy: true, moving: false, stateFresh: true, stationary: true,
      poseFrame: 'robot_flange', flangePositionM: [0.4, 0, 0.2],
      gripperWidthM: 0.080,
    }),
    selectBottle: () => true,
    resetTargetPoseReference: () => true,
    sendRobot: command => { commands.push(command); return true; },
    startGrasp: () => ({ accepted: false, reason: 'simulation_only' }),
  });
  return {
    result: controller.start({ targetId: 1, requestId: 'disabled-smoke' }),
    sent_commands: commands.length,
    robot_control_enabled: false,
  };
}

function runFixture(targetId, fixturePath) {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  if (fixture.schema !== 'thirdhand-alignment-fixture-v1') {
    throw new TypeError('unsupported alignment fixture schema');
  }
  let now = 1000;
  let sequence = 0;
  const robot = {
    connected: true, healthy: true, moving: false, stateFresh: true, stationary: true,
    poseFrame: 'robot_flange', flangePositionM: [0.30, 0, 0.18],
    gripperWidthM: 0.080,
  };
  const commands = [];
  const selections = [];
  const resets = [];
  const handoffs = [];
  const statuses = [];
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
  const controller = new VisualAlignController({
    executionEnabled: true,
    getRobotState: () => ({
      ...robot, flangePositionM: [...robot.flangePositionM],
    }),
    selectBottle: command => { selections.push(command); return true; },
    resetTargetPoseReference: command => { resets.push(command); return true; },
    sendRobot: command => { commands.push(command); return true; },
    startGrasp: handoff => { handoffs.push(handoff); return { accepted: true }; },
    onStatus: status => statuses.push(status),
    nowMs: () => now,
    stableWindow: fixture.stable_frames,
    idFactory: () => `00000000-0000-4000-8000-${String(++sequence).padStart(12, '0')}`,
  });
  const target = () => {
    now += 10;
    const evidenceId = `sha256:${String(now).padStart(64, '0')}`;
    return {
      stableId: targetId,
      requestId: fixture.request_id,
      calibrationId: fixture.calibration_id,
      trackState: 'confirmed',
      motionEpoch: controller.session.motionEpoch,
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
        pointM: fixture.point_m,
        stableSamples: fixture.stable_frames,
        widthM: fixture.width_m,
        approachBase: [1, 0, 0],
        allowed: true,
        blockers: [],
        visionEvidenceId: evidenceId,
        visionConfigId,
        modelProvenance,
      },
    };
  };
  const feed = () => {
    let result;
    for (let index = 0; index < fixture.stable_frames; index += 1) {
      result = controller.onVisionTargets([target()]);
    }
    return result;
  };

  controller.start({ targetId, requestId: fixture.request_id });
  feed();
  robot.flangePositionM = [...commands.at(-1).position];
  controller.onRobotEvent({
    type: 'command_complete', request_id: commands.at(-1).request_id, reached: true,
  });
  feed();
  const phases = statuses.map(status => status.phase)
    .filter(phase => [
      'moving_to_pregrasp', 'settling', 'reobserving', 'handed_off',
    ].includes(phase))
    .filter((phase, index, values) => index === 0 || phase !== values[index - 1])
    .map(phase => phase.toUpperCase());
  return {
    target_id: targetId,
    phases,
    selections,
    pose_resets: resets,
    fake_robot_commands: commands,
    handoffs,
    final: controller.snapshot(),
    robot_control_enabled: false,
  };
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const payload = args.targetId === null && args.fixture === null
    ? disabledSmoke()
    : runFixture(args.targetId, args.fixture);
  console.log(JSON.stringify(payload));
  return 0;
}

if (require.main === module) {
  try { process.exitCode = main(); } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}

module.exports = { main, parseArgs, runFixture };
