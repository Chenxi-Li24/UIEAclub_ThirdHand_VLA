'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const { EventEmitter } = require('node:events');
const {
  SupervisedGraspCli,
  buildObserverArgs,
  failureCategory,
  normalizeObservation,
  parseArgs,
  resolveArtifactPaths,
  startObserver,
  validateSettings,
} = require('../../scripts/grasp_bottle_real');

class FakeBridge extends EventEmitter {
  constructor() {
    super();
    this.sent = [];
    this.started = false;
    this.startCount = 0;
    this.stopped = false;
    this.shutdownCalled = false;
  }
  start() { this.started = true; this.startCount += 1; }
  send(command) { this.sent.push(command); return true; }
  softwareStop() { this.stopped = true; return true; }
  shutdown() { this.shutdownCalled = true; }
}

class ReadyOnlyBridge extends EventEmitter {
  constructor() { super(); this.sent = []; this.startCount = 0; this.shutdownCount = 0; }
  start() { this.startCount += 1; this.emit('bridge_ready', { type: 'bridge_ready' }); }
  send(command) { this.sent.push(command); return true; }
  softwareStop() { return true; }
  shutdown() { this.shutdownCount += 1; }
}

const settings = {
  targetId: 'detection:0',
  maxObservationAgeMs: 300,
  maxCameraWatchdogAgeMs: 500,
  maxRobotAgeMs: 250,
  eulerRad: [0, 0, 0],
  graspOffsetM: [0, 0, 0],
  pregraspHeightM: 0.10,
  liftHeightM: 0.08,
  maxSpeedMps: 0.02,
  maxAngularSpeedRadS: 0.30,
  positionToleranceM: 0.008,
  orientationToleranceRad: 0.12,
  homeJointsDeg: [0, -10, -30, 20, 0, 0],
  homeTcpM: [0.2619276, 0.0004263, 0.0710898],
  safeTransitZM: 0.306371896,
  workspace: { x: [0.15, 0.66], y: [-0.45, 0.45], z: [0.06, 0.65] },
};

function observer(overrides = {}) {
  return {
    event: 'bottle_observation',
  target_id: 'detection:0',
  requested_ordinal: 2,
    locked_detection_id: 0,
    track_state: 'locked',
    frame_id: 10,
    captured_monotonic_ns: 100,
    observed_at_ms: 1900,
    emitted_at_ms: 1910,
    final_frame_age_ms: 10,
    camera_serial: 'XV-1',
    registration_id: 'reg-1',
    pixel_uv: [320, 240],
    camera_xyz_m: [0, 0, 0.3],
    base_xyz_m: [0.40, 0.02, 0.15],
    width_m: 0.055,
    depth_points: 500,
    depth_valid_ratio: 0.9,
    camera_observation_valid: true,
    geometry_valid: true,
    valid: true,
    reason: null,
    robot_state_ts: 1900,
    robot_pose_age_ms: 10,
    robot_pose_blockers: [],
    supervised_base_candidate_valid: true,
    base_transform_approved: false,
    candidate_offset_base_m_applied: [0, 0, 0],
    handeye: {
      calibration_id: 'sha256:' + 'a'.repeat(64),
      effective_matrix_semantics: 'T_sdk_tool_camera',
      physically_validated: false,
    },
    physical_upright_verified: false,
    ...overrides,
  };
}

function referenceObservation(overrides = {}) {
  const row = observer({ frame_id: 200, observed_at_ms: 2050, robot_state_ts: 2050,
    base_xyz_m: [0.40, 0.02, 0.12], ...overrides });
  row.nearfield_reference_candidate = {
    valid: true,
    target_id: row.target_id,
    calibration_id: row.handeye.calibration_id,
    frame_id: row.frame_id,
    observed_at_ms: row.observed_at_ms,
    observation_height_base_m: 0.12,
    bottle_diameter_m: 0.063,
    base_xyz_m: [0.405, 0.02, 0.12],
    source_camera_xyz_m: [...row.camera_xyz_m],
    source_pixel_uv: [...row.pixel_uv],
  };
  return row;
}

function projectionGuard(cli, overrides = {}) {
  const anchor = cli.supervisedAnchor;
  const robot = cli.latestRobot;
  const attached = anchor?.attachment;
  const expected = attached && robot
    ? anchor.base_xyz_m.map((value, index) => value +
      robot.position[index] - attached.contact_tcp_position_m[index])
    : anchor?.base_xyz_m;
  return {
    event: 'bottle_projection_guard',
    trial_id: cli.trialId,
    anchor_id: anchor?.anchor_id,
    target_id: cli.lockedTargetId,
    calibration_id: anchor?.calibration_id,
    frame_id: 300,
    observed_at_ms: cli.nowMs(),
    robot_state_ts: robot?.receivedAtMs,
    robot_pose_blockers: [],
    rgb_observation_valid: true,
    projection_guard_valid: true,
    guard_blockers: [],
    expected_anchor_base_xyz_m: expected,
    projected_anchor_camera_xyz_m: [0.01, 0.02, 0.20],
    pixel_uv: [320, 240],
    ...overrides,
  };
}

assert.equal(parseArgs([]).mode, 'help');
assert.equal(parseArgs(['--simulate', '--settings', JSON.stringify(settings)]).mode, 'simulate');
assert.throws(() => parseArgs(['--live']), /settings/);
assert.equal(normalizeObservation(observer()).calibration_id, 'sha256:' + 'a'.repeat(64));
assert.equal(normalizeObservation(observer({ observed_at_ms: undefined })).valid, false);
assert.equal(failureCategory('target_lost', 'hover'), 'detection');
assert.equal(failureCategory('grasp_height_band_insufficient', 'hover'), 'depth');
assert.equal(failureCategory('calibration_changed', 'descend'), 'calibration');
assert.equal(failureCategory('trajectory_failed', 'hover'), 'hover');
assert.equal(failureCategory('trajectory_failed', 'descend'), 'descend');
assert.equal(failureCategory('object_contact_not_detected', 'close'), 'grasp');
assert.equal(failureCategory('operator_reported_slip', 'holding'), 'slip');
assert.equal(failureCategory('robot_command_timeout', 'hover'), 'robot_command');
assert.equal(validateSettings({ ...settings, fixedGraspBaseZM: 0.13 }).fixedGraspBaseZM, 0.13);
assert.throws(() => validateSettings({ ...settings, fixedGraspBaseZM: Number.NaN }),
  /fixed_grasp_base_z_invalid/);
assert.throws(() => validateSettings({ ...settings, fixedGraspBaseZM: 0.70 }),
  /fixed_grasp_base_z_invalid/);
assert.throws(() => validateSettings({ ...settings, fixedGraspBaseZM: 0.13,
  graspHeightBaseM: 0.13 }), /grasp_height_policy_conflict/);
assert.equal(validateSettings({ ...settings, fixedGraspBaseZM: 0.13,
  observationHeightBaseM: 0.12, bottleDiameterM: 0.063 }).observationHeightBaseM, 0.12);
assert.throws(() => validateSettings({ ...settings, observationHeightBaseM: 0.12,
  graspHeightBaseM: 0.13, bottleDiameterM: 0.063 }), /observation_height_policy_conflict/);
assert.throws(() => validateSettings({ ...settings, observationHeightBaseM: 0.12,
  bottleDiameterM: Number.NaN }), /bottle_diameter_invalid/);
assert.throws(() => validateSettings({ ...settings, observationHeightBaseM: 0.12,
  bottleDiameterM: 0.073 }), /bottle_diameter_invalid/);
assert.equal(validateSettings({ ...settings,
  observerOverlayFile: '/tmp/nearfield-overlay.jpg' }).observerOverlayFile,
  '/tmp/nearfield-overlay.jpg');
assert.throws(() => validateSettings({ ...settings,
  observerOverlayFile: 'relative-overlay.jpg' }), /observer_overlay_file_invalid/);
assert.deepEqual(buildObserverArgs({ settings: { ...settings, targetOrdinal: 1,
  observationHeightBaseM: 0.12, bottleDiameterM: 0.063 } }, {
  visionRoot: '/vision', poseFile: '/pose.json', visionConfig: null, handeyeFile: null,
}), ['/vision/scripts/vision/observe_grasp_bottle.py', '--ordinal', '1', '--allow-camera',
  '--watch-jsonl', '--robot-pose-file', '/pose.json', '--handeye-parent-frame', 'sdk_tool',
  '--observation-height-base-m', '0.12', '--bottle-diameter-m', '0.063']);
assert.deepEqual(buildObserverArgs({ settings: { ...settings, targetOrdinal: 1,
  observerOverlayFile: '/tmp/nearfield-overlay.jpg' } }, {
  visionRoot: '/vision', poseFile: '/pose.json',
}), ['/vision/scripts/vision/observe_grasp_bottle.py', '--ordinal', '1', '--allow-camera',
  '--watch-jsonl', '--robot-pose-file', '/pose.json', '--handeye-parent-frame', 'sdk_tool',
  '--output-overlay', '/tmp/nearfield-overlay.jpg']);
assert.equal(typeof startObserver, 'function');
{
  const livePaths = resolveArtifactPaths({ robotPoseFile: '/tmp/pose.json',
    auditJsonl: '/tmp/audit.jsonl', resultsJsonl: '/tmp/results.jsonl' }, 'live');
  const simulatedPaths = resolveArtifactPaths({ robotPoseFile: '/tmp/pose.json',
    auditJsonl: '/tmp/audit.jsonl', resultsJsonl: '/tmp/results.jsonl' }, 'simulate');
  assert.deepEqual(livePaths, { poseFile: '/tmp/pose.json', auditFile: '/tmp/audit.jsonl',
    resultFile: '/tmp/results.jsonl' });
  assert.deepEqual(simulatedPaths, { poseFile: '/tmp/pose.simulate.json',
    auditFile: '/tmp/audit.simulate.jsonl', resultFile: '/tmp/results.simulate.jsonl' });
  assert.equal(resolveArtifactPaths({ robotPoseFile: '/tmp/pose' }, 'simulate').poseFile,
    '/tmp/pose.simulate');
}

{
  const protocolBridge = new ReadyOnlyBridge();
  let timerCount = 0;
  const protocolCli = new SupervisedGraspCli({
    bridge: protocolBridge, settings, nowMs: () => 2000,
    writeEvent() {}, writeResult() {}, writePose() {},
    setTimer: () => { timerCount += 1; return { unref() {} }; }, clearTimer() {},
  });
  assert.equal(protocolCli.command('connect').ok, true);
  assert.deepEqual(protocolBridge.sent, [{ cmd: 'connect' }],
    'bridge_ready must trigger the explicit Python bridge connect command');
  assert.equal(protocolCli.connected, false, 'bridge_ready alone is not a robot connection');
  assert.equal(protocolCli.command('connect').reason, 'connect_already_requested');
  protocolBridge.emit('bridge_ready', { type: 'bridge_ready' });
  assert.equal(protocolBridge.sent.length, 1, 'a repeated bridge_ready must never reconnect automatically');
  assert.equal(protocolBridge.startCount, 1);
  assert.equal(timerCount, 1);
  protocolBridge.emit('connection', { type: 'connection', connected: true });
  assert.equal(protocolCli.connected, true);
  protocolBridge.emit('connection', { type: 'connection', connected: false, reason: 'bridge_exit:1' });
  assert.equal(protocolBridge.shutdownCount, 1, 'connection loss disables the bridge restart loop');
  protocolBridge.emit('bridge_ready', { type: 'bridge_ready' });
  assert.equal(protocolBridge.sent.length, 1);
}

// A camera seed failure can be recovered only by an explicit, safe, one-shot observe command.
{
  const observeBridge = new FakeBridge();
  const observeSettings = { ...settings };
  delete observeSettings.targetId;
  let observerStarts = 0;
  const observerHandles = [];
  const observeCli = new SupervisedGraspCli({
    bridge: observeBridge, settings: observeSettings, nowMs: () => 2000,
    writeEvent() {}, writeResult() {}, writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
    startObserver() {
      observerStarts += 1;
      const handle = { attempt: observerStarts };
      observerHandles.push(handle);
      return handle;
    },
  });
  assert.equal(observeCli.command('observe').reason, 'robot_disconnected');
  observeCli.command('connect');
  observeBridge.emit('connection', { connected: true });
  observeBridge.emit('robot_state', { tcp_position_m: settings.homeTcpM,
    tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
    state: 'IDLE' });
  assert.equal(observeCli.command('observe').ok, true);
  assert.equal(observerStarts, 1);
  assert.equal(observeCli.command('observe').reason, 'observer_already_running');
  observeCli.observerProcess = null; // The injected observer has emitted exit.
  observeCli.motionActive = true;
  assert.equal(observeCli.command('observe').reason, 'arm_motion_active');
  observeCli.motionActive = false;
  observeCli.holdingObjectPossible = true;
  assert.equal(observeCli.command('observe').reason, 'holding_object_possible');
  observeCli.holdingObjectPossible = false;
  observeCli.lockedTargetId = 'detection:0';
  assert.equal(observeCli.command('observe').reason, 'target_identity_already_locked_start_new_session');
  assert.equal(observerStarts, 1, 'a locked target must never be silently rebound by a new seed');
  observeCli.lockedTargetId = null;
  assert.equal(observeCli.command('observe').ok, true);
  assert.equal(observerStarts, 2, 'each retry requires a new explicit operator command');
  assert.equal(observeCli.observerProcess, observerHandles[1]);
}

let now = 2000;
let poseTick;
let guardFrame = 100;
function completeCartesianStage(cli, testBridge, phase, clock = () => now, onCommand = () => {}) {
  let last;
  let count = 0;
  while (cli.snapshot().phase === phase) {
    last = testBridge.sent.at(-1);
    onCommand(last);
    const sentCount = testBridge.sent.length;
    testBridge.emit('motion_state', { state: 'MOVING', request_id: last.request_id });
    testBridge.emit('command_complete', {
      type: 'command_complete', command: 'move_l', request_id: last.request_id,
      reached: true, position_error_m: 0.002, orientation_error_rad: 0.01,
    });
    testBridge.emit('motion_state', { state: 'IDLE', request_id: last.request_id });
    if (cli.snapshot().phase === phase && testBridge.sent.length === sentCount) {
      const tick = clock();
      cli.observerLine(JSON.stringify(observer({ frame_id: ++guardFrame,
        observed_at_ms: tick - 1, camera_observation_valid: true, valid: false,
        geometry_valid: false, width_m: null, base_xyz_m: null,
        supervised_base_candidate_valid: false,
        robot_pose_blockers: ['pose_does_not_cover_frame_capture'] })));
      assert.equal(testBridge.sent.length, sentCount,
        'a frame captured before stationary_since must only wait');
      testBridge.emit('robot_state', { tcp_position_m: last.position,
        tcp_euler_rad: last.euler, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
        state: 'IDLE' });
      cli.observerLine(JSON.stringify(observer({ frame_id: ++guardFrame,
        observed_at_ms: tick, robot_state_ts: tick })));
    } else {
      testBridge.emit('robot_state', { tcp_position_m: last.position,
        tcp_euler_rad: last.euler, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
        state: 'IDLE' });
    }
    assert.equal(++count < 100, true);
  }
  return last;
}

function completeProjectionStage(cli, testBridge, phase, advanceClock) {
  let count = 0;
  while (cli.snapshot().phase === phase) {
    const command = testBridge.sent.at(-1);
    const sentCount = testBridge.sent.length;
    testBridge.emit('motion_state', { state: 'MOVING', request_id: command.request_id });
    testBridge.emit('command_complete', { command: 'move_l', request_id: command.request_id,
      reached: true, position_error_m: 0.002, orientation_error_rad: 0.01 });
    testBridge.emit('motion_state', { state: 'IDLE', request_id: command.request_id });
    advanceClock();
    testBridge.emit('robot_state', { ts: cli.nowMs(), tcp_position_m: command.position,
      tcp_euler_rad: command.euler,
      joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
    if (cli.snapshot().phase === phase && testBridge.sent.length === sentCount) {
      cli.observerLine(JSON.stringify(projectionGuard(cli, { frame_id: 300 + count })));
    }
    assert.equal(++count < 100, true);
  }
}
const output = [];
const results = [];
const poses = [];
const bridge = new FakeBridge();
const cli = new SupervisedGraspCli({
  bridge,
  settings,
  nowMs: () => now,
  writeEvent: event => output.push(event),
  writeResult: event => results.push(event),
  writePose: pose => poses.push(pose),
  setTimer: callback => { poseTick = callback; return { unref() {} }; },
  clearTimer: () => {},
});
const fixedHeightPreview = cli._preview({
  graspHeightPolicy: 'fixed_base_z', fixedGraspBaseZM: 0.13,
});
assert.equal(fixedHeightPreview.grasp_height_policy, 'fixed_base_z');
assert.equal(fixedHeightPreview.fixed_grasp_base_z_m, 0.13);

assert.equal(cli.command('connect').ok, true);
assert.equal(bridge.started, true);
bridge.emit('connection', { type: 'connection', connected: true });
bridge.emit('robot_state', {
  type: 'robot_state', joints_rad: [0, 0, 0, 0, 0, 0],
  tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0], state: 'IDLE',
});
assert.deepEqual(poses.at(-1), {
  pose_frame: 'sdk_tool', tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: [0, 0, 0], ts: 2000, stationary: true, stationary_since_ms: 2000,
  trial_id: cli.trialId, controller_phase: 'idle', controller_state_phase: 'idle',
  pending_phase: null, supervised_anchor: null,
});
now = 2250;
poseTick();
assert.equal(poses.at(-1).ts, 2000, 'the pose writer must not refresh an old robot sample timestamp');
now = 2000;

cli.observerLine(JSON.stringify(observer()));
assert.equal(cli.command('hover').reason, 'home_not_verified');

assert.equal(cli.command('home').ok, true);
assert.equal(bridge.sent.at(-1).cmd, 'move_joint');
assert.equal(bridge.sent.at(-1).source, 'preset:home');
bridge.emit('command_complete', {
  type: 'command_complete', command: 'move_joint',
  request_id: bridge.sent.at(-1).request_id,
});
bridge.emit('robot_state', {
  type: 'robot_state', joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0], state: 'IDLE',
});
assert.equal(cli.command('open').ok, true);
assert.equal(bridge.sent.at(-1).cmd, 'gripper');
assert.equal(bridge.sent.at(-1).position, 1);
assert.equal(bridge.sent.at(-1).kp, 8);
assert.equal(bridge.sent.at(-1).kd, 0.1);
assert.equal(bridge.sent.at(-1).source, 'grasp:supervised_open');
bridge.emit('command_complete', {
  type: 'command_complete', command: 'gripper', request_id: bridge.sent.at(-1).request_id,
  reached: true, moved: true, actual_position: 0.997,
});

cli.observerLine(JSON.stringify(observer()));
const hoverResult = cli.command('hover');
assert.equal(hoverResult.ok, true, JSON.stringify({hoverResult,latest:cli.latestObservation}));
let hover = bridge.sent.at(-1);
assert.deepEqual(hover.position.slice(0, 2), settings.homeTcpM.slice(0, 2));
assert.equal(hover.position[2] > settings.homeTcpM[2], true);
assert.deepEqual(hover.euler, [0, 0, 0]);
assert.equal(hover.source, 'grasp:supervised_hover');
const hoverCommands = [];
hover = completeCartesianStage(cli, bridge, 'hover', () => now,
  command => hoverCommands.push(command));
assert.equal(hoverCommands.some(command =>
  command.position[2] === settings.safeTransitZM && command.position[0] === settings.homeTcpM[0]), true);
assert.equal(hoverCommands.some(command =>
  command.position[2] === settings.safeTransitZM && command.position[0] === 0.40), true);
assert.deepEqual(hover.position, [0.40, 0.02, 0.25]);

now = 2050;
cli.observerLine(JSON.stringify(observer({ frame_id: 11, observed_at_ms: 2040, robot_state_ts: 2040 })));
assert.equal(cli.command('descend').ok, true);
let descend = bridge.sent.at(-1);
assert.equal(descend.source, 'grasp:supervised_descend');
descend = completeCartesianStage(cli, bridge, 'descend');

now = 2100;
cli.observerLine(JSON.stringify(observer({ frame_id: 12, observed_at_ms: 2090, robot_state_ts: 2090 })));
bridge.emit('robot_state', {
  type: 'robot_state', joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  tcp_position_m: [0.40, 0.02, 0.15], tcp_euler_rad: settings.eulerRad, state: 'IDLE',
});
assert.equal(cli.command('close').ok, true);
const close = bridge.sent.at(-1);
assert.equal(close.cmd, 'gripper');
assert.equal(close.position, 0);
assert.equal(close.kp, 2);
assert.equal(close.kd, 0.1);
assert.equal(close.source, 'grasp:supervised_close');
assert.equal(cli.gripperOpen, false, 'issuing close immediately revokes the open-gripper gate');
now = 2110;
cli.observerLine(JSON.stringify(observer({ frame_id: 13, observed_at_ms: 2110, robot_state_ts: 2110 })));
now = 2120;
bridge.emit('command_complete', {
  type: 'command_complete', command: 'gripper', request_id: close.request_id,
  reached: false, moved: true, actual_position: 0.58,
});
assert.equal(cli.command('lift').ok, false,
  'a frame captured before close completed cannot authorize lift');

now = 2150;
bridge.emit('robot_state', {
  type: 'robot_state', joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  tcp_position_m: [0.40, 0.02, 0.15], tcp_euler_rad: settings.eulerRad, state: 'IDLE',
});
cli.observerLine(JSON.stringify(observer({ frame_id: 14, observed_at_ms: 2150, robot_state_ts: 2150 })));
assert.equal(cli.command('lift').ok, true);
let lift = bridge.sent.at(-1);
assert.equal(lift.source, 'grasp:supervised_lift');
lift = completeCartesianStage(cli, bridge, 'lift');
now = 5200;
bridge.emit('robot_state', {
  type: 'robot_state', tcp_position_m: [0.40, 0.02, 0.23], tcp_euler_rad: [0, 0, 0],
  joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE',
});
assert.equal(cli.command('confirm success').ok, true);
assert.equal(results.length, 1);
assert.equal(results[0].success, true);
assert.equal(results[0].visual_confirmation.bottle_bottom_lifted_5cm_for_3s, true);
assert.equal(cli.command('confirm success').reason, 'trial_result_already_recorded');
assert.equal(results.length, 1);
assert.equal(cli.command('home').reason, 'holding_object');
assert.equal(cli.command('open').reason, 'use_open_supported');
assert.equal(bridge.shutdownCalled, false, 'successful hold keeps the bridge and process alive');
assert.equal(cli.command('quit').ok, false);
assert.equal(cli.command('quit supported').ok, true);
assert.equal(bridge.shutdownCalled, true);

// A manually approved Home RGB-D reference freezes the anchor before the first hover segment.
{
  let anchorNow = 2000;
  const anchorBridge = new FakeBridge();
  const anchorEvents = [];
  const anchorPoses = [];
  const anchorResults = [];
  const anchorSettings = { ...settings, targetOrdinal: 2, fixedGraspBaseZM: 0.13,
    observationHeightBaseM: 0.12, bottleDiameterM: 0.063 };
  const anchorCli = new SupervisedGraspCli({
    bridge: anchorBridge, settings: anchorSettings, nowMs: () => anchorNow,
    writeEvent: event => anchorEvents.push(event), writeResult: result => anchorResults.push(result),
    writePose: pose => anchorPoses.push(pose), setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  anchorCli.command('connect');
  anchorBridge.emit('connection', { connected: true });
  anchorBridge.emit('robot_state', { ts: anchorNow, tcp_position_m: settings.homeTcpM,
    tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
    state: 'IDLE' });
  anchorCli.homeVerified = true;
  anchorCli.gripperOpen = true;
  anchorCli.observerLine(JSON.stringify(referenceObservation({ observed_at_ms: anchorNow,
    robot_state_ts: anchorNow })));
  assert.equal(anchorCli.command('hover').ok, true);
  assert.ok(anchorCli.supervisedAnchor?.anchor_id);
  assert.deepEqual(anchorCli.supervisedAnchor.base_xyz_m, [0.405, 0.02, 0.12]);
  assert.deepEqual(anchorCli.controller.state.plan.graspM, [0.40, 0.02, 0.13],
    'the reference checks the frozen command; it does not move the approved plan');
  assert.equal(anchorCli.supervisedAnchor.reference.frame_id, 200);
  assert.equal(anchorPoses.at(-1).controller_phase, 'hover');
  assert.equal(anchorPoses.at(-1).pending_phase, 'hover');
  assert.equal(anchorPoses.at(-1).supervised_anchor.anchor_id,
    anchorCli.supervisedAnchor.anchor_id);
  assert.equal(anchorEvents.some(event => event.type === 'nearfield_anchor_approved' &&
    event.plan_reference_xy_discrepancy_m === 0.005), true);

  const firstHover = anchorBridge.sent.at(-1);
  const sentDuringMotion = anchorBridge.sent.length;
  anchorBridge.emit('motion_state', { state: 'MOVING', request_id: firstHover.request_id });
  anchorNow = 2060;
  anchorCli.observerLine(JSON.stringify(projectionGuard(anchorCli, {
    frame_id: 301, robot_pose_blockers: ['pose_not_stationary'],
    projection_guard_valid: false, guard_blockers: ['pose_not_stationary'],
    expected_anchor_base_xyz_m: null, projected_anchor_camera_xyz_m: null, pixel_uv: null,
  })));
  assert.equal(anchorCli.snapshot().phase, 'hover',
    'motion requires fresh locked RGB but does not require a projection pose');
  assert.equal(anchorBridge.sent.length, sentDuringMotion);

  anchorBridge.emit('command_complete', { command: 'move_l', request_id: firstHover.request_id,
    reached: true, position_error_m: 0.002, orientation_error_rad: 0.01 });
  anchorBridge.emit('motion_state', { state: 'IDLE', request_id: firstHover.request_id });
  anchorNow = 2070;
  anchorBridge.emit('robot_state', { ts: anchorNow, tcp_position_m: firstHover.position,
    tcp_euler_rad: firstHover.euler,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  anchorCli.observerLine(JSON.stringify(projectionGuard(anchorCli, {
    frame_id: 302, anchor_id: 'wrong-anchor', projection_guard_valid: false,
    guard_blockers: ['anchor_mismatch'], expected_anchor_base_xyz_m: null,
  })));
  assert.equal(anchorCli.snapshot().phase, 'aborted');
  assert.equal(anchorCli.snapshot().reason, 'anchor_mismatch');
  assert.equal(anchorResults[0].failure_phase, 'hover');
  assert.equal(anchorCli.pending, null,
    'abort while waiting after a completed segment clears pending immediately');
  assert.equal(anchorCli.command('new trial').ok, true,
    'completed-segment abort can recover without restarting the SDK');
  assert.equal(anchorBridge.sent.some(command => command.cmd === 'gripper' && command.position === 0), false);
}

// A verified close attaches the frozen anchor; lift guards must follow actual TCP translation.
{
  let ttlNow = 300000;
  const ttlBridge = new FakeBridge();
  const ttlCli = new SupervisedGraspCli({ bridge: ttlBridge,
    settings: { ...settings, observationHeightBaseM: 0.12, bottleDiameterM: 0.063,
      fixedGraspBaseZM: 0.13 }, nowMs: () => ttlNow,
    writeEvent() {}, writeResult() {}, writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {} });
  ttlCli.connected = true;
  ttlCli.stationarySinceMs = 0;
  const calibrationId = 'sha256:' + 'a'.repeat(64);
  const frozenPlan = { identityId: 'detection:0', calibrationId,
    graspM: [0.40, 0.02, 0.13], pregraspM: [0.40, 0.02, 0.28],
    retreatM: [0.40, 0.02, 0.21], yawRad: 0, widthM: 0.063,
    observedAtMs: 0, previewId: 'ttl' };
  ttlCli.supervisedAnchor = { anchor_id: 'ttl-anchor', trial_id: ttlCli.trialId,
    target_id: 'detection:0', calibration_id: calibrationId, approved_at_ms: 0,
    base_xyz_m: [0.405, 0.02, 0.12], reference: { frame_id: 1, observed_at_ms: 0 } };
  ttlCli.lockedTargetId = 'detection:0';
  ttlCli.controller.state = { phase: 'hover', mode: 'step', reason: null, nextPhase: null,
    inFlight: null, plan: frozenPlan, identityId: 'detection:0', calibrationId };
  ttlCli.controller.latestTarget = frozenPlan;
  ttlCli.latestRobot = { position: settings.homeTcpM, euler: settings.eulerRad,
    joints: [], receivedAtMs: ttlNow };
  ttlCli.observerLine(JSON.stringify(projectionGuard(ttlCli, { frame_id: 2 })));
  assert.equal(ttlCli.latestProjectionGuard.frame_id, 2,
    'an exactly 300 second old immutable anchor remains usable with fresh frame evidence');
  ttlNow = 300001;
  ttlCli.latestRobot.receivedAtMs = ttlNow;
  ttlCli.observerLine(JSON.stringify(projectionGuard(ttlCli, { frame_id: 3 })));
  assert.equal(ttlCli.snapshot().reason, 'anchor_stale',
    'the immutable anchor expires immediately after the fixed 300 second limit');
}

// A verified close attaches the frozen anchor; lift guards must follow actual TCP translation.
{
  let attachNow = 3000;
  const attachBridge = new FakeBridge();
  const attachPoses = [];
  const attachSettings = { ...settings, fixedGraspBaseZM: 0.13,
    observationHeightBaseM: 0.12, bottleDiameterM: 0.063 };
  const attachCli = new SupervisedGraspCli({ bridge: attachBridge, settings: attachSettings,
    nowMs: () => attachNow, writeEvent() {}, writeResult() {},
    writePose: pose => attachPoses.push(pose), setTimer: () => ({ unref() {} }), clearTimer() {} });
  attachCli.command('connect');
  attachBridge.emit('connection', { connected: true });
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: settings.homeTcpM,
    tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
    state: 'IDLE' });
  attachCli.homeVerified = true;
  attachCli.gripperOpen = true;
  attachCli.observerLine(JSON.stringify(referenceObservation({ observed_at_ms: attachNow,
    robot_state_ts: attachNow })));
  assert.equal(attachCli.command('hover').ok, true);
  completeProjectionStage(attachCli, attachBridge, 'hover', () => { attachNow += 10; });
  attachNow += 10;
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: [0.40, 0.02, 0.28],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, { frame_id: 390 })));
  assert.equal(attachCli.command('descend').ok, true);
  completeProjectionStage(attachCli, attachBridge, 'descend', () => { attachNow += 10; });
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, {
    frame_id: 399, observed_at_ms: attachCli.stationarySinceMs - 1,
    projection_guard_valid: false, guard_blockers: ['pose_unavailable'],
    robot_pose_blockers: ['pose_does_not_cover_frame_capture'],
    expected_anchor_base_xyz_m: null, projected_anchor_camera_xyz_m: null, pixel_uv: null,
  })));
  assert.equal(attachCli.snapshot().phase, 'preview_ready',
    'an old in-flight frame after the final descend segment must wait for a new static frame');
  attachNow += 10;
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: [0.40, 0.02, 0.13],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, { frame_id: 400 })));
  attachNow += 350;
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: [0.40, 0.02, 0.13],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  assert.equal(attachCli.command('close').reason, 'target_stale',
    'a 350 ms projection cannot authorize close even before the 500 ms stream watchdog');
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: [0.40, 0.02, 0.13],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, { frame_id: 401 })));
  assert.equal(attachCli.command('close').ok, true);
  const closeCommand = attachBridge.sent.at(-1);
  attachNow += 10;
  attachBridge.emit('command_complete', { command: 'gripper', request_id: closeCommand.request_id,
    reached: false, moved: true, actual_position: 0.58 });
  assert.deepEqual(attachCli.supervisedAnchor.attachment.contact_tcp_position_m,
    [0.40, 0.02, 0.13]);
  assert.equal(attachCli.supervisedAnchor.attachment.contact_verified_at_ms, attachNow);
  assert.deepEqual(attachPoses.at(-1).supervised_anchor.attachment,
    attachCli.supervisedAnchor.attachment);

  attachNow += 10;
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: [0.40, 0.02, 0.13],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, { frame_id: 402 })));
  assert.equal(attachCli.command('lift').ok, true);
  const liftSegment = attachBridge.sent.at(-1);
  attachBridge.emit('motion_state', { state: 'MOVING', request_id: liftSegment.request_id });
  attachBridge.emit('command_complete', { command: 'move_l', request_id: liftSegment.request_id,
    reached: true, position_error_m: 0.002, orientation_error_rad: 0.01 });
  attachBridge.emit('motion_state', { state: 'IDLE', request_id: liftSegment.request_id });
  attachNow += 10;
  attachBridge.emit('robot_state', { ts: attachNow, tcp_position_m: liftSegment.position,
    tcp_euler_rad: liftSegment.euler,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  const expectedLiftAnchor = attachCli.supervisedAnchor.base_xyz_m.map((value, index) =>
    value + liftSegment.position[index] - [0.40, 0.02, 0.13][index]);
  attachCli.observerLine(JSON.stringify(projectionGuard(attachCli, { frame_id: 403,
    expected_anchor_base_xyz_m: expectedLiftAnchor })));
  assert.deepEqual(attachCli.latestProjectionGuard.expected_anchor_base_xyz_m, expectedLiftAnchor);
}

// Contact failure latches the controller and prevents lift.
const bridge2 = new FakeBridge();
const results2 = [];
const cli2 = new SupervisedGraspCli({
  bridge: bridge2, settings, nowMs: () => 2000,
  writeEvent() {}, writeResult: event => results2.push(event), writePose() {},
  setTimer: () => ({ unref() {} }), clearTimer() {},
});
cli2.command('connect');
bridge2.emit('connection', { connected: true });
bridge2.emit('robot_state', {
  tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0], state: 'IDLE',
});
cli2.observerLine(JSON.stringify(observer()));
cli2.homeVerified = true;
cli2.gripperOpen = true;
cli2.command('hover');
let sent;
sent = completeCartesianStage(cli2, bridge2, 'hover', () => 2000);
cli2.observerLine(JSON.stringify(observer({ frame_id: 11, observed_at_ms: 2000, robot_state_ts: 2000 })));
assert.equal(cli2.command('descend').ok, true);
sent = completeCartesianStage(cli2, bridge2, 'descend', () => 2000);
cli2.observerLine(JSON.stringify(observer({ frame_id: 12, observed_at_ms: 2000, robot_state_ts: 2000 })));
const close2 = cli2.command('close');
assert.equal(close2.ok, true, JSON.stringify({close2, state:cli2.snapshot(), observation:cli2.latestObservation}));
sent = bridge2.sent.at(-1);
bridge2.emit('command_complete', { command: 'gripper', request_id: sent.request_id,
  reached: true, moved: true, actual_position: 0 });
assert.equal(cli2.snapshot().phase, 'aborted');
assert.equal(cli2.command('lift').ok, false);
assert.equal(results2.length, 1);
assert.equal(results2[0].reason, 'object_contact_not_detected');
assert.equal(results2[0].failure_category, 'grasp');

// Consume the actual near-field producer fixture without repairing or filling its fields in JS.
{
  const fixturePath = '/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill/tests/fixtures/integration/' +
    'observer-producer-nearfield-contract.jsonl';
  const rows = fs.readFileSync(fixturePath, 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(rows.map(row => row.scenario), ['fresh_hover_reference',
    'stationary_projection_no_new_depth', 'motion_rgb_only', 'target_lost']);
  assert.equal(rows[1].raw_depth_used, false);
  assert.equal(rows[2].rgb_observation_valid, true);
  assert.equal(rows[2].projection_guard_valid, false);
  assert.equal(rows[2].projected_anchor_camera_xyz_m, null);

  let fixtureNow = rows[1].emitted_at_ms;
  const fixtureBridge = new FakeBridge();
  const fixtureResults = [];
  const fixtureCli = new SupervisedGraspCli({ bridge: fixtureBridge,
    settings: { ...settings, targetOrdinal: 1, targetId: rows[0].target_id,
      fixedGraspBaseZM: 0.13, observationHeightBaseM: 0.12, bottleDiameterM: 0.063 },
    nowMs: () => fixtureNow, writeEvent() {}, writeResult: result => fixtureResults.push(result),
    writePose() {}, setTimer: () => ({ unref() {} }), clearTimer() {} });
  fixtureCli.trialId = rows[1].trial_id;
  fixtureCli.command('connect');
  fixtureBridge.emit('connection', { connected: true });
  fixtureBridge.emit('robot_state', { ts: fixtureNow, tcp_position_m: [0.4493, -0.00949, 0.28],
    tcp_euler_rad: settings.eulerRad,
    joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180), state: 'IDLE' });
  fixtureCli.stationarySinceMs = 9800;
  fixtureCli.observerLine(JSON.stringify(rows[0]));
  fixtureCli.homeVerified = true;
  fixtureCli.gripperOpen = true;
  assert.equal(fixtureCli.command('hover').ok, true);
  fixtureCli.supervisedAnchor.anchor_id = rows[1].anchor_id;
  const sentBeforeMotionGuard = fixtureBridge.sent.length;
  fixtureCli.motionActive = true;
  fixtureCli.observerLine(JSON.stringify(rows[2]));
  assert.equal(fixtureCli.snapshot().phase, 'hover');
  assert.equal(fixtureBridge.sent.length, sentBeforeMotionGuard);

  fixtureCli.motionActive = false;
  fixtureCli.stationarySinceMs = 9800;
  fixtureCli.pending.awaitingGuard = true;
  fixtureCli.pending.segmentCompletedAtMs = 9800;
  fixtureCli.pending.segmentStartFrameId = rows[1].frame_id - 1;
  fixtureCli.latestRobot.receivedAtMs = fixtureNow;
  fixtureCli.observerLine(JSON.stringify(rows[1]));
  assert.equal(fixtureBridge.sent.length, sentBeforeMotionGuard + 1,
    'the unmodified producer projection row authorizes the next bounded segment');

  fixtureCli.motionActive = true;
  fixtureCli.observerLine(JSON.stringify(rows[3]));
  assert.equal(fixtureCli.snapshot().phase, 'aborted');
  assert.equal(fixtureCli.snapshot().reason, 'target_lost');
  assert.equal(fixtureResults[0].failure_phase, 'hover');
  assert.equal(fixtureBridge.sent.some(command => command.cmd === 'gripper' && command.position === 0), false);
}

// Consume the actual legacy Python producer fixture without repairing or filling its fields in JS.
{
  const fixturePath = '/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill/tests/fixtures/integration/' +
    'observer-producer-motion-contract.jsonl';
  const rows = fs.readFileSync(fixturePath, 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(rows.map(row => row.scenario), [
    'stationary_initial_height_band_valid',
    'motion_camera_tracking_only',
    'idle_old_inflight_camera_tracking_only',
    'stationary_new_height_band_valid',
  ]);
  assert.equal(rows[1].camera_observation_valid, true);
  assert.equal(rows[1].camera_xyz_semantics, 'robust_mask_median_tracking_only');
  assert.equal(rows[1].pixel_uv_semantics, 'mask_centroid_tracking_only');
  assert.equal(rows[1].geometry_valid, false);
  assert.equal(rows[1].supervised_base_candidate_valid, false);
  assert.equal(rows[1].base_xyz_m, null);

  let contractNow = rows[0].emitted_at_ms;
  const contractBridge = new FakeBridge();
  const contractEvents = [];
  const contractSettings = { ...settings, targetOrdinal: 1, targetId: 'detection:0',
    graspHeightBaseM: 0.13 };
  const contractCli = new SupervisedGraspCli({
    bridge: contractBridge, settings: contractSettings, nowMs: () => contractNow,
    writeEvent: event => contractEvents.push(event), writeResult() {}, writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  contractCli.command('connect');
  contractBridge.emit('connection', { connected: true });
  contractBridge.emit('robot_state', { ts: rows[0].robot_state_ts,
    tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0],
    joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
  contractCli.observerLine(JSON.stringify(rows[0]));
  assert.equal(contractCli.latestObservation.frame_id, rows[0].frame_id);
  contractCli.homeVerified = true;
  contractCli.gripperOpen = true;
  assert.equal(contractCli.command('hover').ok, true);
  const firstSegment = contractBridge.sent.at(-1);
  const sentAfterFirstSegment = contractBridge.sent.length;

  contractNow = rows[1].emitted_at_ms;
  contractBridge.emit('motion_state', { state: 'MOVING', request_id: firstSegment.request_id });
  contractCli.observerLine(JSON.stringify(rows[1]));
  assert.equal(contractCli.snapshot().phase, 'hover');
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment);
  assert.equal(contractEvents.some(event => event.type === 'observer_motion_frame' &&
    event.frame_id === rows[1].frame_id), true);

  contractNow = rows[2].emitted_at_ms;
  contractBridge.emit('command_complete', { command: 'move_l', request_id: firstSegment.request_id,
    reached: true, position_error_m: 0.002, orientation_error_rad: 0.01 });
  contractBridge.emit('motion_state', { state: 'IDLE', request_id: firstSegment.request_id });
  contractCli.observerLine(JSON.stringify(rows[2]));
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment,
    'the old in-flight frame cannot authorize the next segment after IDLE');

  contractNow = rows[3].emitted_at_ms;
  contractBridge.emit('robot_state', { ts: rows[3].robot_state_ts,
    tcp_position_m: firstSegment.position, tcp_euler_rad: firstSegment.euler,
    joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
  contractCli.observerLine(JSON.stringify(rows[3]));
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment + 1,
    'only a new stationary height-band frame plus a new robot sample may send the next segment');
  assert.equal(contractCli.snapshot().phase, 'hover');
}

// The no-height producer contract keeps measured Base XY while the pure plan applies fixed Z.
{
  const fixturePath = '/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill/tests/fixtures/integration/' +
    'observer-producer-fixed-z-contract.jsonl';
  const rows = fs.readFileSync(fixturePath, 'utf8').trim().split('\n').map(JSON.parse);
  assert.deepEqual(rows.map(row => row.scenario), [
    'fixed_z_stationary_initial_axis_valid',
    'fixed_z_motion_camera_tracking_only',
    'fixed_z_idle_old_inflight_camera_tracking_only',
    'fixed_z_stationary_new_axis_valid',
  ]);
  assert.equal(rows[0].grasp_height_base_m, null);
  assert.equal(rows[1].camera_observation_valid, true);
  assert.equal(rows[1].camera_xyz_semantics, 'robust_mask_median_tracking_only');
  assert.equal(rows[1].geometry_valid, false);
  assert.equal(rows[1].supervised_base_candidate_valid, false);
  assert.equal(rows[1].base_xyz_m, null);

  let contractNow = rows[0].emitted_at_ms;
  const contractBridge = new FakeBridge();
  const contractEvents = [];
  const contractSettings = { ...settings, targetOrdinal: 1, targetId: 'detection:0',
    fixedGraspBaseZM: 0.13 };
  const contractCli = new SupervisedGraspCli({
    bridge: contractBridge, settings: contractSettings, nowMs: () => contractNow,
    writeEvent: event => contractEvents.push(event), writeResult() {}, writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  contractCli.command('connect');
  contractBridge.emit('connection', { connected: true });
  contractBridge.emit('robot_state', { ts: rows[0].robot_state_ts,
    tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0],
    joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
  contractCli.observerLine(JSON.stringify(rows[0]));
  assert.deepEqual(contractCli.controller.latestTarget.graspM,
    [Number(rows[0].base_xyz_m[0].toFixed(9)), Number(rows[0].base_xyz_m[1].toFixed(9)), 0.13]);
  const fixedPreview = contractCli._preview(contractCli.controller.latestTarget);
  assert.equal(fixedPreview.grasp_height_policy, 'fixed_base_z');
  assert.equal(fixedPreview.fixed_grasp_base_z_m, 0.13);
  contractCli.homeVerified = true;
  contractCli.gripperOpen = true;
  assert.equal(contractCli.command('hover').ok, true);
  const firstSegment = contractBridge.sent.at(-1);
  const sentAfterFirstSegment = contractBridge.sent.length;

  contractNow = rows[1].emitted_at_ms;
  contractBridge.emit('motion_state', { state: 'MOVING', request_id: firstSegment.request_id });
  contractCli.observerLine(JSON.stringify(rows[1]));
  assert.equal(contractCli.snapshot().phase, 'hover');
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment);
  assert.equal(contractEvents.some(event => event.type === 'observer_motion_frame' &&
    event.frame_id === rows[1].frame_id), true);

  contractNow = rows[2].emitted_at_ms;
  contractBridge.emit('command_complete', { command: 'move_l', request_id: firstSegment.request_id,
    reached: true, position_error_m: 0.002, orientation_error_rad: 0.01 });
  contractBridge.emit('motion_state', { state: 'IDLE', request_id: firstSegment.request_id });
  contractCli.observerLine(JSON.stringify(rows[2]));
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment,
    'fixed-Z mode must not authorize the next segment from an old in-flight frame');

  contractNow = rows[3].emitted_at_ms;
  contractBridge.emit('robot_state', { ts: rows[3].robot_state_ts,
    tcp_position_m: firstSegment.position, tcp_euler_rad: firstSegment.euler,
    joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
  contractCli.observerLine(JSON.stringify(rows[3]));
  assert.equal(contractBridge.sent.length, sentAfterFirstSegment + 1,
    'fixed-Z mode still requires a new stationary producer frame and robot sample');
  assert.deepEqual(contractCli.controller.latestTarget.graspM,
    [Number(rows[3].base_xyz_m[0].toFixed(9)), Number(rows[3].base_xyz_m[1].toFixed(9)), 0.13]);
  assert.equal(contractCli.snapshot().phase, 'hover');
}

// Producer failure rows remain fail-closed: zero depth and stale capture abort without closing.
for (const failure of ['depth', 'stale']) {
  const fixturePath = '/home/nieqingcao/th0814/VA/PinZiZhuaQuSkill/tests/fixtures/integration/' +
    'observer-producer-motion-contract.jsonl';
  const rows = fs.readFileSync(fixturePath, 'utf8').trim().split('\n').map(JSON.parse);
  let failureNow = rows[0].emitted_at_ms;
  const failureBridge = new FakeBridge();
  const failureCli = new SupervisedGraspCli({
    bridge: failureBridge, settings: { ...settings, targetOrdinal: 1, targetId: 'detection:0' },
    nowMs: () => failureNow, writeEvent() {}, writeResult() {}, writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  failureCli.command('connect');
  failureBridge.emit('connection', { connected: true });
  failureBridge.emit('robot_state', { ts: rows[0].robot_state_ts,
    tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0],
    joints_rad: settings.homeJointsDeg.map(value => value * Math.PI / 180), state: 'IDLE' });
  failureCli.observerLine(JSON.stringify(rows[0]));
  failureCli.homeVerified = true;
  failureCli.gripperOpen = true;
  failureCli.command('hover');
  const sentBeforeFailure = failureBridge.sent.length;
  failureNow = rows[1].emitted_at_ms;
  failureBridge.emit('motion_state', { state: 'MOVING' });
  const invalid = failure === 'depth'
    ? { ...rows[1], camera_observation_valid: false, camera_xyz_m: null, depth_points: 0,
      reason: 'depth_points_insufficient', reasons: ['depth_points_insufficient'] }
    : { ...rows[1], observed_at_ms: failureNow - settings.maxObservationAgeMs - 1 };
  failureCli.observerLine(JSON.stringify(invalid));
  assert.equal(failureCli.snapshot().phase, 'aborted');
  assert.equal(failureBridge.sent.length, sentBeforeFailure);
  assert.equal(failureBridge.sent.some(command => command.cmd === 'gripper' && command.position === 0), false);
  assert.equal(failureCli.command('close').ok, false);
}

// Motion-only pose/width blockers are tolerated; actual camera loss latches after the current segment.
const bridge3 = new FakeBridge();
const events3 = [];
const cli3 = new SupervisedGraspCli({
  bridge: bridge3, settings, nowMs: () => 2000,
  writeEvent: event => events3.push(event), writeResult() {}, writePose() {},
  setTimer: () => ({ unref() {} }), clearTimer() {},
});
cli3.command('connect');
bridge3.emit('connection', { connected: true });
bridge3.emit('robot_state', {
  tcp_position_m: settings.homeTcpM, tcp_euler_rad: [0, 0, 0], state: 'IDLE',
});
cli3.observerLine(JSON.stringify(observer()));
cli3.homeVerified = true;
cli3.gripperOpen = true;
cli3.command('hover');
cli3.motionActive = true;
cli3.observerLine(JSON.stringify(observer({ valid: false, geometry_valid: false, width_m: null,
  supervised_base_candidate_valid: false, base_xyz_m: null,
  robot_pose_blockers: ['pose_not_stationary', 'pose_does_not_cover_frame_capture'] })));
assert.equal(cli3.snapshot().phase, 'hover');
cli3.motionActive = false;
const sentBeforeLoss = bridge3.sent.length;
const boundedSegment = bridge3.sent.at(-1);
cli3.observerLine(JSON.stringify(observer({ valid: false, camera_observation_valid: false,
  track_state: 'lost', reason: 'target_lost' })));
assert.equal(cli3.snapshot().phase, 'aborted');
assert.equal(bridge3.stopped, false);
assert.equal(events3.some(e => e.type === 'motion_cancel_latched' &&
  e.motion_stop_mode === 'after_current_bounded_segment'), true);
bridge3.emit('command_complete', { command: 'move_l', request_id: boundedSegment.request_id,
  reached: true, position_error_m: 0, orientation_error_rad: 0 });
assert.equal(bridge3.sent.length, sentBeforeLoss, 'target loss sends no segment after the current bounded one');
assert.equal(cli3.command('close').ok, false);

// Motion-only pose blockers never hide identity or calibration changes.
const bridge4 = new FakeBridge();
const cli4 = new SupervisedGraspCli({
  bridge: bridge4, settings, nowMs: () => 2000,
  writeEvent() {}, writeResult() {}, writePose() {},
  setTimer: () => ({ unref() {} }), clearTimer() {},
});
cli4.command('connect');
bridge4.emit('connection', { connected: true });
bridge4.emit('robot_state', { tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: [0, 0, 0], state: 'IDLE' });
cli4.observerLine(JSON.stringify(observer()));
cli4.homeVerified = true;
cli4.gripperOpen = true;
cli4.command('hover');
cli4.motionActive = true;
cli4.observerLine(JSON.stringify(observer({ target_id: 'detection:9',
  supervised_base_candidate_valid: false,
  robot_pose_blockers: ['pose_not_stationary', 'pose_does_not_cover_frame_capture'] })));
assert.equal(cli4.snapshot().phase, 'aborted');
assert.equal(cli4.snapshot().reason, 'target_identity_changed');

// The in-motion watchdog uses the measured 500 ms stream-gap ceiling without relaxing 300 ms stage gates.
let watchNow = 2000;
let watchTick;
const bridge5 = new FakeBridge();
const cli5 = new SupervisedGraspCli({
  bridge: bridge5, settings, nowMs: () => watchNow,
  writeEvent() {}, writeResult() {}, writePose() {},
  setTimer: callback => { watchTick = callback; return { unref() {} }; }, clearTimer() {},
});
cli5.command('connect');
bridge5.emit('connection', { connected: true });
bridge5.emit('robot_state', { tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  state: 'IDLE' });
cli5.observerLine(JSON.stringify(observer()));
cli5.homeVerified = true;
cli5.gripperOpen = true;
cli5.command('hover');
watchNow = 2399;
watchTick();
assert.equal(cli5.snapshot().phase, 'hover');
watchNow = 2401;
watchTick();
assert.equal(cli5.snapshot().phase, 'aborted');
assert.equal(cli5.snapshot().reason, 'observer_watchdog_stale');

// Target loss during close leaves the gripper in an unknown/possibly-holding state.
let closeLossNow = 2000;
const bridge6 = new FakeBridge();
const closeLossResults = [];
const cli6 = new SupervisedGraspCli({
  bridge: bridge6, settings, nowMs: () => closeLossNow,
  writeEvent() {}, writeResult: event => closeLossResults.push(event), writePose() {},
  setTimer: () => ({ unref() {} }), clearTimer() {},
});
cli6.command('connect');
bridge6.emit('connection', { connected: true });
bridge6.emit('robot_state', { tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  state: 'IDLE' });
cli6.observerLine(JSON.stringify(observer()));
cli6.homeVerified = true;
cli6.gripperOpen = true;
cli6.command('hover');
completeCartesianStage(cli6, bridge6, 'hover', () => closeLossNow);
cli6.observerLine(JSON.stringify(observer({ frame_id: 501, observed_at_ms: 2000, robot_state_ts: 2000 })));
assert.equal(cli6.command('descend').ok, true);
completeCartesianStage(cli6, bridge6, 'descend', () => closeLossNow);
bridge6.emit('robot_state', { tcp_position_m: [0.4, 0.02, 0.15],
  tcp_euler_rad: settings.eulerRad, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  state: 'IDLE' });
cli6.observerLine(JSON.stringify(observer({ frame_id: 502, observed_at_ms: 2000, robot_state_ts: 2000 })));
assert.equal(cli6.command('close').ok, true);
const uncertainClose = bridge6.sent.at(-1);
cli6.observerLine(JSON.stringify(observer({ camera_observation_valid: false, valid: false,
  track_state: 'lost', reason: 'target_lost' })));
bridge6.emit('command_complete', { command: 'gripper', request_id: uncertainClose.request_id,
  reached: false, moved: true, actual_position: 0.58 });
assert.equal(cli6.gripperOpen, false);
assert.equal(cli6.command('hover').ok, false);
assert.equal(cli6.command('home').reason, 'holding_object_possible');
assert.equal(cli6.command('open').reason, 'use_open_supported');
assert.equal(cli6.command('open supported').ok, true);
const recoveryOpen = bridge6.sent.at(-1);
bridge6.emit('command_complete', { command: 'gripper', request_id: recoveryOpen.request_id,
  reached: true, moved: true, actual_position: 0.997 });
assert.equal(cli6.gripperOpen, true);
assert.equal(cli6.holdingObjectPossible, false);
assert.equal(closeLossResults[0].reason, 'target_lost');
assert.equal(closeLossResults[0].failure_category, 'detection');

// An unacknowledged bridge command cannot leave the CLI permanently in arm_motion_active.
let timeoutNow = 2000;
let timeoutTick;
const bridge7 = new FakeBridge();
const timeoutResults = [];
const cli7 = new SupervisedGraspCli({
  bridge: bridge7, settings: { ...settings, commandTimeoutGraceMs: 5000,
    gripperCommandTimeoutMs: 5000 }, nowMs: () => timeoutNow,
  writeEvent() {}, writeResult: event => timeoutResults.push(event), writePose() {},
  setTimer: callback => { timeoutTick = callback; return { unref() {} }; }, clearTimer() {},
});
cli7.command('connect');
bridge7.emit('connection', { connected: true });
bridge7.emit('robot_state', { tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: [0, 0, 0], joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  state: 'IDLE' });
cli7.observerLine(JSON.stringify(observer()));
cli7.homeVerified = true;
cli7.gripperOpen = true;
cli7.command('hover');
const timedOutCommand = bridge7.sent.at(-1);
timeoutNow = 2000 + timedOutCommand.time_sec * 1000 + 5001;
timeoutTick();
assert.equal(cli7.snapshot().phase, 'aborted');
assert.equal(cli7.snapshot().reason, 'robot_command_timeout');
assert.equal(cli7.pending, null);
assert.equal(timeoutResults[0].reason, 'robot_command_timeout');
assert.equal(timeoutResults[0].failure_category, 'robot_command');
bridge7.emit('robot_state', { tcp_position_m: settings.homeTcpM,
  tcp_euler_rad: settings.eulerRad, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
  state: 'IDLE' });
const timeoutTrialId = cli7.trialId;
const timeoutSent = bridge7.sent.length;
assert.equal(cli7.command('new trial').ok, true,
  'a previously verified open gripper is sufficient to start another trial');
assert.notEqual(cli7.trialId, timeoutTrialId);
assert.equal(bridge7.sent.length, timeoutSent);
assert.equal(bridge7.startCount, 1, 'new trial must not restart the SDK bridge');

// An operator-confirmed holding failure records its stated category without inventing vision data.
{
  const reportBridge = new FakeBridge();
  const reportResults = [];
  const reportCli = new SupervisedGraspCli({
    bridge: reportBridge, settings, nowMs: () => 6000,
    writeEvent() {}, writeResult: result => reportResults.push(result), writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  reportCli.command('connect');
  reportBridge.emit('connection', { connected: true });
  reportBridge.emit('robot_state', { tcp_position_m: [0.4, 0.02, 0.23],
    tcp_euler_rad: settings.eulerRad, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
    state: 'IDLE' });
  reportCli.controller.state = { phase: 'holding', mode: 'step', reason: null,
    nextPhase: null, inFlight: null };
  reportCli.holdStartedAtMs = 2000;
  reportCli.descendMeasuredZ = 0.15;
  reportCli.contact = true;
  assert.equal(reportCli.command('confirm failure').reason, 'confirm_failure_requires_category');
  assert.equal(reportResults.length, 0);
  assert.equal(reportCli.command('confirm failure slip').ok, true);
  assert.equal(reportResults[0].success, false);
  assert.equal(reportResults[0].failure_category, 'slip');
  assert.equal(reportResults[0].reason, 'operator_reported_slip');
  assert.equal(reportResults[0].failure_source, 'operator_confirmation');
  assert.equal(reportResults[0].observation, undefined);
}

// A failed open can start another empty trial without reconnecting or sending a robot command.
{
  const retryBridge = new FakeBridge();
  const retryResults = [];
  const retryCli = new SupervisedGraspCli({
    bridge: retryBridge, settings, nowMs: () => 7000,
    writeEvent() {}, writeResult: result => retryResults.push(result), writePose() {},
    setTimer: () => ({ unref() {} }), clearTimer() {},
  });
  retryCli.command('connect');
  retryBridge.emit('connection', { connected: true });
  retryBridge.emit('robot_state', { tcp_position_m: settings.homeTcpM,
    tcp_euler_rad: settings.eulerRad, joints_rad: settings.homeJointsDeg.map(v => v * Math.PI / 180),
    state: 'IDLE' });
  assert.equal(retryCli.command('open').ok, true);
  const failedOpen = retryBridge.sent.at(-1);
  retryBridge.emit('command_complete', { command: 'gripper', request_id: failedOpen.request_id,
    reached: false, moved: true, actual_position: 0.956132 });
  assert.equal(retryResults[0].failure_category, 'robot_command');
  const previousTrialId = retryCli.trialId;
  const lockedTargetId = retryCli.lockedTargetId;
  const sentBeforeReset = retryBridge.sent.length;
  assert.equal(retryCli.command('new trial').reason,
    'new_trial_requires_verified_open_or_explicit_empty');
  assert.equal(retryCli.command('new trial empty').ok, true);
  assert.notEqual(retryCli.trialId, previousTrialId);
  assert.equal(retryCli.lockedTargetId, lockedTargetId);
  assert.equal(retryCli.resultRecorded, false);
  assert.equal(retryCli.snapshot().phase, 'aborted');
  assert.equal(retryCli.latestObservation, null);
  assert.equal(retryCli.controller.latestTarget, null);
  assert.equal(retryCli.homeVerified, false);
  assert.equal(retryCli.gripperOpen, false);
  assert.equal(retryBridge.sent.length, sentBeforeReset);
  assert.equal(retryBridge.startCount, 1);
  retryCli.observerLine(JSON.stringify(observer({ frame_id: 701, observed_at_ms: 6999,
    robot_state_ts: 6999, base_xyz_m: [0.42, 0.02, 0.15] })));
  assert.equal(retryCli.latestObservation, null, 'a frame captured before new trial cannot authorize it');
  retryCli.observerLine(JSON.stringify(observer({ frame_id: 702, observed_at_ms: 7000,
    robot_state_ts: 7000, base_xyz_m: [0.42, 0.02, 0.15] })));
  assert.equal(retryCli.latestObservation.frame_id, 702);
  assert.equal(retryCli.lockedTargetId, lockedTargetId,
    'the same locked identity may provide a fresh pose in the new trial');
  assert.equal(retryCli.command('new trial empty').reason, 'current_trial_not_finished');
}

console.log('PASS supervised grasp CLI is staged, evidence-bound, contact-gated and hold-preserving');
