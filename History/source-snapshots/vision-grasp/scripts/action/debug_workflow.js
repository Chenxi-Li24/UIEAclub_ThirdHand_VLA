#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const { EventEmitter } = require('node:events');
const { WorkflowClient } = require('../../src/thirdhand_va/action/grasp/workflow');

function parseArgs(argv) {
  const result = { targetId: null, fixture: null };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--target-id') result.targetId = Number(argv[++index]);
    else if (argv[index] === '--fixture') result.fixture = argv[++index];
    else throw new TypeError(`unknown argument: ${argv[index]}`);
  }
  if (!Number.isSafeInteger(result.targetId) || result.targetId < 1 ||
      result.targetId > 5 || !result.fixture) {
    throw new TypeError('usage: debug_workflow.js --target-id 1..5 --fixture FILE');
  }
  return result;
}

function runFixture(targetId, fixturePath) {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  if (fixture.schema !== 'thirdhand-va-full-cycle-fixture-v1' ||
      fixture.target_id !== targetId) throw new TypeError('full-cycle fixture mismatch');
  let now = 1000;
  let frame = 0;
  const cameraCommands = [];
  const robotCommands = [];
  const statuses = [];
  const finishes = [];
  const actionConfigId = `sha256:${'a'.repeat(64)}`;
  const visionConfigId = `sha256:${'b'.repeat(64)}`;
  const pathValidationId = `sha256:${'d'.repeat(64)}`;
  const modelProvenance = {
    vision_config_id: visionConfigId,
    camera_registration_id: 'debug-registration',
    camera_mount_id: 'debug-wrist-mount',
    grounding_model: 'debug/grounding',
    grounding_revision: '1'.repeat(40),
    grounding_weights_sha256: `sha256:${'e'.repeat(64)}`,
    sam_model: 'debug/sam',
    sam_revision: '2'.repeat(40),
    sam_weights_sha256: `sha256:${'f'.repeat(64)}`,
  };
  const robotState = {
    connected: true,
    moving: false,
    stationary: true,
    stateFresh: true,
    healthy: true,
    poseFrame: 'robot_flange',
    flangePositionM: [0.30, 0, 0.18],
    flangeEulerRad: [0, 0, 0],
    jointsDeg: [0, 0, 0, 0, 0, 0],
    velocitiesDegS: [0, 0, 0, 0, 0, 0],
    gripperWidthM: 0.080,
    observedMonotonicNs: 1000,
  };
  const cameraBridge = new EventEmitter();
  cameraBridge.send = message => {
    cameraCommands.push(message);
    if (message.type === 'release_bottle') {
      cameraBridge.emit('selection_release_status', {
        type: 'selection_release_status', request_id: message.request_id,
        status: 'released', robot_control_enabled: false,
      });
    }
    return true;
  };
  cameraBridge.sendArmState = () => true;
  const robotClient = {
    send(command) { robotCommands.push(command); return true; },
    getRobotState() {
      return { ...robotState, flangePositionM: [...robotState.flangePositionM] };
    },
  };
  const config = {
    execution_enabled: true,
    content_id: actionConfigId,
    workflow_timeout_ms: 10000,
    robot: {
      home_tolerance_deg: 0.5,
      presets: { home: [0, 0, 0, 0, 0, 0] },
    },
    workspace_m: { x: [0.15, 0.66], y: [-0.45, 0.45], z: [0.04, 0.65] },
    motion: {
      pregrasp_offset_m: 0.10,
      lift_height_m: 0.12,
      max_refine_step_m: 0.005,
      linear_speed_m_s: 0.03,
      grasp_euler_rad: [0, 0, 0],
    },
    gripper: {
      execution_max_width_m: 0.072,
      contact_min_width_m: 0.008,
      contact_max_width_m: 0.070,
      release_min_width_m: 0.074,
      physical_max_width_m: 0.080,
    },
    grasp: {
      flange_offset_base_m: fixture.flange_offset_base_m,
      offset_validated: true,
    },
    place: {
      strategy: 'fixed_xy_keep_grasp_z',
      validated: true,
      fixed_xy_m: fixture.fixed_place_xy_m,
      euler_rad: fixture.place_euler_rad,
      grasp_z_range_m: fixture.grasp_z_range_m,
      vertical_clearance_m: fixture.vertical_clearance_m,
      home_preset: 'home',
      path_validation_id: pathValidationId,
    },
  };
  const workflow = new WorkflowClient({
    cameraBridge,
    robotClient,
    config,
    nowMs: () => now,
    workflowTimeoutMs: 10000,
    store: { write(status) { statuses.push(status); } },
    onFinish: result => finishes.push(result),
  });
  const target = motionEpoch => {
    now += 10;
    frame += 1;
    const evidenceId = `sha256:${String(frame).padStart(64, '0')}`;
    return {
      actionable: true,
      stableId: targetId,
      requestId: fixture.request_id,
      calibrationId: fixture.calibration_id,
      trackState: 'confirmed',
      motionEpoch,
      depthValid: true,
      armStationary: true,
      gripperReady: true,
      calibrationValidated: true,
      safetyApproved: true,
      blockers: [],
      observedAtMs: now,
      evidenceId,
      visionConfigId,
      modelProvenance,
      posePositionStdM: [0.001, 0.001, 0.002],
      preview: {
        previewId: `sha256:${String(frame + 100).padStart(64, '0')}`,
        pointM: fixture.point_m,
        stableSamples: fixture.stable_frames,
        widthM: fixture.width_m,
        approachBase: [1, 0, 0],
        calibrationId: fixture.calibration_id,
        armStateId: `sha256:${String(frame + 200).padStart(64, '0')}`,
        visionEvidenceId: evidenceId,
        visionConfigId,
        modelProvenance,
        allowed: true,
        blockers: [],
      },
    };
  };
  const feed = epoch => {
    for (let index = 0; index < fixture.stable_frames; index += 1) {
      workflow.onVisionResult({ targets: [target(epoch)] });
    }
  };

  workflow.start({ targetId, requestId: fixture.request_id });
  feed(0);
  let command = robotCommands.at(-1);
  robotState.flangePositionM = [...command.position];
  workflow.onRobotEvent({
    type: 'command_complete', command: command.cmd,
    request_id: command.request_id, reached: true,
  });
  feed(1);
  while (workflow.snapshot().active) {
    command = robotCommands.at(-1);
    const closing = command.source === 'grasp:close';
    const releasing = command.source === 'grasp:release';
    workflow.onRobotEvent({
      type: 'command_complete', command: command.cmd,
      request_id: command.request_id,
      reached: closing ? false : true,
      actual_width_m: closing ? fixture.contact_width_m : releasing ? 0.080 : undefined,
      actualJointsDeg: command.source === 'grasp:return_home'
        ? [0, 0, 0, 0, 0, 0] : undefined,
      robot_healthy: true,
    });
  }
  return {
    target_id: targetId,
    camera_commands: cameraCommands,
    robot_command_sources: robotCommands.map(command => command.source),
    fake_robot_commands: robotCommands,
    status_trace: statuses,
    result: finishes.at(-1),
    robot_control_enabled: false,
  };
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  console.log(JSON.stringify(runFixture(args.targetId, args.fixture)));
  return 0;
}

if (require.main === module) {
  try { process.exitCode = main(); } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}

module.exports = { main, parseArgs, runFixture };
