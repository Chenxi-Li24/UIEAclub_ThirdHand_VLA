#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

const { loadActionConfig } = require('../../src/thirdhand_va/action/config');
const { CameraBridge } = require('../../src/thirdhand_va/action/adapters/camera_bridge');
const { createRobotClient, REAL_ACK } = require(
  '../../src/thirdhand_va/action/adapters/robot_client_factory'
);
const { authorizePregraspValidation } = require(
  '../../src/thirdhand_va/action/calibration/pregrasp_validation'
);
const { evaluateHomeState } = require('../../src/thirdhand_va/action/safety/home_gate');
const { HomeCoordinator } = require(
  '../../src/thirdhand_va/action/safety/home_coordinator'
);

const USAGE = [
  'usage: validate_handeye_pregrasp.js --target-id 1..5 --allow-robot [options]',
  '  --config FILE       Action config (default: configs/action.yaml)',
  '  --calibration FILE  pending v3 hand-eye artifact',
  '  --dwell-ms N        high-clearance observation time, 1000..10000 (default: 3000)',
  'clearance-only: no grasp offset, no orientation change, no descent, no gripper command',
  'requires THIRDHAND_LIVE_TEST=1, THIRDHAND_ALLOW_ROBOT and',
  'THIRDHAND_VA_ALLOW_CAMERA=1; missing gates fail before hardware startup',
].join('\n');

function parseArgs(argv) {
  const result = {
    allowRobot: false,
    help: false,
    targetId: null,
    config: 'configs/action.yaml',
    calibration: 'configs/calibration/lumos-handeye.pending.json',
    dwellMs: 3000,
    timeoutMs: 180000,
  };
  const values = new Map([
    ['--target-id', 'targetId'], ['--config', 'config'],
    ['--calibration', 'calibration'], ['--dwell-ms', 'dwellMs'],
    ['--timeout-ms', 'timeoutMs'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--allow-robot') result.allowRobot = true;
    else if (arg === '--help') result.help = true;
    else if (values.has(arg)) {
      const value = argv[++index];
      if (!value) throw new TypeError(`missing value for ${arg}`);
      result[values.get(arg)] = value;
    } else throw new TypeError(`unknown argument: ${arg}`);
  }
  result.targetId = Number(result.targetId);
  result.dwellMs = Number(result.dwellMs);
  result.timeoutMs = Number(result.timeoutMs);
  if (!result.help && (!Number.isSafeInteger(result.targetId) || result.targetId < 1 ||
      result.targetId > 5)) throw new TypeError('--target-id must be within [1, 5]');
  if (!Number.isSafeInteger(result.dwellMs) || result.dwellMs < 1000 ||
      result.dwellMs > 10000) throw new TypeError('--dwell-ms must be within [1000, 10000]');
  if (!Number.isSafeInteger(result.timeoutMs) || result.timeoutMs < 30000 ||
      result.timeoutMs > 300000) throw new TypeError('--timeout-ms is invalid');
  return Object.freeze(result);
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function isRetryableValidationReason(reason) {
  return [
    'robot_not_stationary',
    'validation_target_stale',
    'validation_target_invalid',
    'validation_preview_pending',
  ].includes(reason);
}

async function waitUntil(predicate, timeoutMs, reason) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = predicate();
    if (value) return value;
    await delay(50);
  }
  throw new Error(reason);
}

function createStartupHomeCoordinator({
  robotClient,
  config,
  HomeCoordinatorClass = HomeCoordinator,
}) {
  return new HomeCoordinatorClass({
    robotClient,
    homePreset: config.place.home_preset,
    homeJointsDeg: config.robot.presets[config.place.home_preset],
    toleranceDeg: config.robot.home_tolerance_deg,
    startupValidated: config.place.startup_home_validated,
    startupJointRangesDeg: config.place.startup_joint_ranges_deg,
    timeoutMs: config.home_timeout_ms,
  });
}

async function waitForHomeCoordinator(
  homeCoordinator,
  timeoutMs,
  { start = true } = {}
) {
  if (start) {
    const started = homeCoordinator.start();
    if (started.accepted !== true) {
      throw new Error(started.reason || 'startup_home_failed');
    }
  }
  return waitUntil(() => {
    const snapshot = homeCoordinator.snapshot();
    if (snapshot.phase === 'failed') {
      throw new Error(snapshot.reason || 'startup_home_failed');
    }
    return snapshot.ready === true ? snapshot : null;
  }, timeoutMs, 'startup_home_timeout');
}

async function waitForFreshHomeState({
  robotClient,
  boundaryStateSequence,
  homeJointsDeg,
  toleranceDeg,
  timeoutMs,
}) {
  if (!Number.isSafeInteger(boundaryStateSequence) || boundaryStateSequence < 1) {
    throw new Error('home_state_boundary_missing');
  }
  return waitUntil(() => {
    const state = robotClient.getRobotState();
    if (!Number.isSafeInteger(state?.stateSequence) ||
        state.stateSequence <= boundaryStateSequence) return null;
    const home = evaluateHomeState({
      robotState: state,
      homeJointsDeg,
      toleranceDeg,
    });
    return home.allowed === true ? Object.freeze({ state, home }) : null;
  }, timeoutMs, 'home_not_verified');
}

function waitForCommand(robotClient, command, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error(`${command.source}:timeout`));
    }, timeoutMs);
    const onEvent = event => {
      if (event?.request_id !== command.request_id ||
          !['command_complete', 'error'].includes(event.type)) return;
      cleanup();
      if (event.type === 'error' || (command.cmd !== 'software_stop' &&
          event.reached !== true)) reject(new Error(
        event.reason || `${command.source}:not_reached`
      ));
      else resolve(event);
    };
    function cleanup() {
      clearTimeout(timeout);
      robotClient.off('event', onEvent);
    }
    robotClient.on('event', onEvent);
    if (robotClient.send(command) !== true) {
      cleanup();
      reject(new Error(`${command.source}:transport_unavailable`));
    }
  });
}

async function acknowledgedSoftwareCleanup(robotClient, source) {
  const event = await waitForCommand(robotClient, {
    cmd: 'software_stop', request_id: randomUUID(), source, reason: source,
  }, 10000);
  if (event.cleanupAcknowledged !== true ||
      !['simulation', 'vendor_cleanup_returned'].includes(
        event.cleanupConfirmationMode
      ) || event.controlReleased !== true ||
      event.depowerIndependentlyConfirmed !== false) {
    throw new Error('software_stop_not_confirmed');
  }
}

function buildClearanceObservationReport({
  targetId,
  plan,
  overlayFile = null,
  createdAt = new Date().toISOString(),
} = {}) {
  return Object.freeze({
    schema: 'thirdhand-handeye-clearance-observation-v1',
    created_at: createdAt,
    target_id: targetId,
    calibration_id: plan.calibrationId,
    preview_id: plan.previewId,
    detected_grasp_m: plan.detectedGraspM,
    observation_m: plan.observationM,
    stages: plan.stages,
    grasp_offset_applied: false,
    orientation_changed: false,
    commands_descent: false,
    gripper_commanded: false,
    returned_home: true,
    software_cleanup_acknowledged: true,
    cleanup_confirmation_mode: 'vendor_cleanup_returned',
    depower_independently_confirmed: false,
    requires_operator_confirmation: true,
    eligible_for_handeye_approval: false,
    overlay_file: overlayFile,
  });
}

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const env = dependencies.env || process.env;
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  let args;
  try { args = parseArgs(argv); } catch (error) {
    writeError(error.message);
    return 2;
  }
  if (args.help) {
    write(USAGE);
    return 0;
  }
  const blockers = [];
  if (!args.allowRobot) blockers.push('allow_robot_flag_missing');
  if (env.THIRDHAND_LIVE_TEST !== '1') blockers.push('live_test_env_missing');
  if (env.THIRDHAND_ALLOW_ROBOT !== REAL_ACK) blockers.push('live_robot_ack_missing');
  if (env.THIRDHAND_VA_ALLOW_CAMERA !== '1') {
    blockers.push('camera_access_ack_missing');
  }
  if (blockers.length) {
    write(JSON.stringify({ status: 'blocked', reasons: blockers }));
    return 2;
  }

  const projectRoot = path.resolve(__dirname, '../..');
  const configPath = path.resolve(projectRoot, args.config);
  const calibrationPath = path.resolve(projectRoot, args.calibration);
  if (!fs.existsSync(calibrationPath)) {
    writeError(`calibration file missing: ${calibrationPath}`);
    return 2;
  }
  let config;
  try { config = loadActionConfig(configPath); } catch (error) {
    writeError(`action config invalid: ${error.message}`);
    return 2;
  }

  const cameraBridge = dependencies.cameraBridge || new CameraBridge({
    projectRoot,
    python: config.robot.python_executable,
    onlineEnabled: true,
    calibrationFile: calibrationPath,
  });
  const robotClient = dependencies.robotClient || createRobotClient(config, {
    realAuthorization: env.THIRDHAND_ALLOW_ROBOT,
  });
  const homeCoordinator = dependencies.homeCoordinator ||
    createStartupHomeCoordinator({ robotClient, config });
  let latestDetection = null;
  let selectionSent = false;
  let motionStarted = false;
  let lastTargetSummary = null;
  let lastDecisionReason = null;
  let lastRobotSummary = null;
  const recentRobotSamples = [];
  const requestId = randomUUID();
  const onRobot = event => {
    if (event?.type !== 'robot_state') return;
    lastRobotSummary = {
      state_sequence: event.stateSequence,
      moving: event.moving,
      stationary: event.stationary,
      state_fresh: event.stateFresh,
      healthy: event.healthy,
      joints_deg: event.jointsDeg,
      velocities_deg_s: event.velocitiesDegS,
      flange_position_m: event.flangePositionM,
    };
    recentRobotSamples.push(lastRobotSummary);
    if (recentRobotSamples.length > 20) recentRobotSamples.shift();
    cameraBridge.sendArmState(
      event.flangePositionM, event.flangeEulerRad, event.jointsDeg,
      event.velocitiesDegS, event.stationary, event.observedMonotonicNs
    );
  };
  const onDetection = event => { latestDetection = event; };
  robotClient.on('event', onRobot);
  cameraBridge.on('detection_result', onDetection);
  cameraBridge.on('log', event => write(JSON.stringify(event)));

  try {
    const homeStart = homeCoordinator.start();
    if (homeStart.accepted !== true) {
      throw new Error(homeStart.reason || 'startup_home_failed');
    }
    if (robotClient.connect() !== true) throw new Error('robot_start_failed');
    await waitForHomeCoordinator(
      homeCoordinator,
      config.home_timeout_ms + 5000,
      { start: false }
    );

    cameraBridge.start();
    await waitUntil(() => cameraBridge.getInfo().ready === true, 120000, 'camera_ready_timeout');
    selectionSent = cameraBridge.send({
      type: 'select_bottle', stable_id: args.targetId, request_id: requestId,
    });
    if (!selectionSent) throw new Error('selection_transport_unavailable');

    const plan = await waitUntil(() => {
      const target = latestDetection?.targets?.find(item =>
        item.stable_id === args.targetId && item.selected === true
      );
      if (!target) {
        lastDecisionReason = 'selected_target_missing';
        lastTargetSummary = {
          visible_ids: latestDetection?.targets?.map(item => item.stable_id) ?? [],
          status: latestDetection?.status ?? null,
          reasons: latestDetection?.reasons ?? [],
        };
        return null;
      }
      lastTargetSummary = {
        stable_id: target.stable_id,
        track_state: target.track_state,
        depth_valid: target.depth_valid,
        blockers: target.blockers,
        has_grasp_preview: Boolean(target.grasp_preview),
        preview_blockers: target.grasp_preview?.blockers ?? null,
        stable_samples: target.grasp_preview?.stable_samples ?? null,
      };
      const decision = authorizePregraspValidation({
        targetId: args.targetId,
        target,
        robot: robotClient.getRobotState(),
        config,
        nowMs: Date.now(),
      });
      lastDecisionReason = decision.approved === true ? null : decision.reason;
      if (decision.approved === true) return decision;
      if (!isRetryableValidationReason(decision.reason)) {
        throw new Error(decision.reason);
      }
      return null;
    }, args.timeoutMs, 'validation_target_timeout');

    motionStarted = true;
    for (const stage of plan.stages) {
      write(JSON.stringify({ type: 'commissioning_stage', phase: stage.phase,
        position_m: stage.position, euler_rad: stage.euler }));
      await waitForCommand(robotClient, {
        cmd: 'move_l', position: stage.position, euler: stage.euler,
        time_sec: stage.timeSec, request_id: randomUUID(),
        source: `handeye_validation:${stage.phase}`,
      }, Math.ceil(stage.timeSec * 1000) + 15000);
    }

    await delay(args.dwellMs);
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const outputDir = path.join(
      projectRoot, 'artifacts/action/commissioning', `handeye-pregrasp-${stamp}`
    );
    fs.mkdirSync(outputDir, { recursive: true });
    const snapshot = cameraBridge.getLatestVisionSnapshot();
    const overlayPath = path.join(outputDir, 'overlay.jpg');
    if (snapshot?.jpeg) fs.writeFileSync(overlayPath, snapshot.jpeg);

    const homeBoundaryState = robotClient.getRobotState();
    await waitForCommand(robotClient, {
      cmd: 'preset', name: config.place.home_preset,
      request_id: randomUUID(), source: 'handeye_validation:return_home',
    }, config.home_timeout_ms + 10000);
    await waitForFreshHomeState({
      robotClient,
      boundaryStateSequence: homeBoundaryState?.stateSequence,
      homeJointsDeg: config.robot.presets[config.place.home_preset],
      toleranceDeg: config.robot.home_tolerance_deg,
      timeoutMs: 5000,
    });
    await acknowledgedSoftwareCleanup(robotClient, 'handeye_validation:complete');
    motionStarted = false;

    const report = buildClearanceObservationReport({
      targetId: args.targetId,
      plan,
      overlayFile: snapshot?.jpeg ? 'overlay.jpg' : null,
    });
    const reportPath = path.join(outputDir, 'report.json');
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
    write(JSON.stringify({ status: 'awaiting_operator_confirmation',
      report: reportPath, overlay: snapshot?.jpeg ? overlayPath : null,
      robot_at_home: true, cleanup_acknowledged: true,
      depower_independently_confirmed: false }));
    return 0;
  } catch (error) {
    writeError(`hand-eye pregrasp validation failed: ${error.message}`);
    if (lastDecisionReason !== null || lastTargetSummary !== null) {
      write(JSON.stringify({ type: 'commissioning_blocker',
        reason: lastDecisionReason, target: lastTargetSummary,
        robot: lastRobotSummary, robot_samples: recentRobotSamples }));
    }
    if (motionStarted && robotClient.protocolReady === true) {
      try {
        await acknowledgedSoftwareCleanup(
          robotClient, 'handeye_validation:failure'
        );
      } catch {}
    }
    return 1;
  } finally {
    if (selectionSent) cameraBridge.send({
      type: 'release_bottle', request_id: requestId,
    });
    cameraBridge.shutdown();
    homeCoordinator.shutdown();
    robotClient.shutdown();
    robotClient.off('event', onRobot);
    cameraBridge.off('detection_result', onDetection);
  }
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}

module.exports = {
  buildClearanceObservationReport,
  createStartupHomeCoordinator,
  isRetryableValidationReason,
  main,
  parseArgs,
  waitForHomeCoordinator,
  waitForFreshHomeState,
};
