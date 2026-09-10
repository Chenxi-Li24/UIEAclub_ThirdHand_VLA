'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const test = require('node:test');

const { WorkflowClient } = require(
  '../../../src/thirdhand_va/action/grasp/workflow'
);

const HOME = [0, 15, -30, 5, 0, 0];

function homeConfig(overrides = {}) {
  return {
    execution_enabled: true,
    ...overrides,
    robot: {
      presets: { home: HOME }, home_tolerance_deg: 0.5,
      ...(overrides.robot ?? {}),
    },
    place: { home_preset: 'home', ...(overrides.place ?? {}) },
  };
}

function acknowledgingCamera(sendOverride = () => true) {
  const bridge = new EventEmitter();
  bridge.send = message => {
    const sent = sendOverride(message);
    if (sent === true && message.type === 'release_bottle') {
      bridge.emit('selection_release_status', {
        type: 'selection_release_status', request_id: message.request_id,
        status: 'released',
      });
    }
    return sent;
  };
  bridge.sendArmState = () => true;
  return bridge;
}

test('workflow rejects a bottle number unless the robot is currently at Home', () => {
  let alignmentStarts = 0;
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      send() { return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        jointsDeg: [0, 15, -30, 5, 0, 1],
      }; },
    },
    config: {
      execution_enabled: true,
      robot: { presets: { home: HOME }, home_tolerance_deg: 0.5 },
      place: { home_preset: 'home' },
    },
    createAlignmentController: () => ({
      active: false,
      start() { alignmentStarts += 1; return { accepted: true }; },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
      cancel() { return { accepted: true }; },
    }),
  });

  assert.deepEqual(workflow.start({ targetId: 1, requestId: 'not-home' }), {
    accepted: false, reason: 'robot_not_at_home',
  });
  assert.equal(alignmentStarts, 0);
  assert.equal(workflow.snapshot().active, false);
});

test('workflow owns local alignment and grasp without high-level robot delegation', () => {
  const cameraMessages = [];
  const robotMessages = [];
  const alignmentStarts = [];
  const visionInputs = [];
  const graspPlans = [];
  const finishes = [];
  const forwardedArmStates = [];
  let alignDependencies;
  let graspDependencies;
  const cameraBridge = new EventEmitter();
  cameraBridge.send = message => { cameraMessages.push(message); return true; };
  cameraBridge.sendArmState = (...args) => { forwardedArmStates.push(args); return true; };
  const workflow = new WorkflowClient({
    cameraBridge,
    robotClient: {
      send(message) { robotMessages.push(message); return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange',
        flangePositionM: [0.3, 0, 0.18], jointsDeg: [...HOME],
      }; },
    },
    config: homeConfig({
      grasp: { flange_offset_base_m: [0.0475, 0.01, 0], offset_validated: true },
    }),
    store: { write() {} },
    planBuilder: handoff => ({ ...handoff, schema: 'fixture-plan' }),
    createGraspController: dependencies => {
      graspDependencies = dependencies;
      return {
        active: false,
        start(plan) {
          graspPlans.push(plan);
          dependencies.onStatus({ phase: 'complete', evidenceId: plan.evidenceId });
          return { accepted: true };
        },
        onRobotEvent() { return { handled: false }; },
        cancel() { return { accepted: true }; },
      };
    },
    createAlignmentController: dependencies => {
      alignDependencies = dependencies;
      return {
        active: true,
        start(request) {
          alignmentStarts.push(request);
          dependencies.selectBottle({
            type: 'select_bottle', stable_id: request.targetId,
            request_id: request.requestId,
          });
          return { accepted: true, phase: 'acquiring' };
        },
        onVisionTargets(targets) {
          visionInputs.push(targets);
          return dependencies.startGrasp({
            stableId: 2, requestId: 'req-2', evidenceId: `sha256:${'a'.repeat(64)}`,
          });
        },
        onRobotEvent() { return { handled: false }; },
        cancel() { return { accepted: true }; },
      };
    },
    onFinish: result => finishes.push(result),
  });

  assert.equal(workflow.start({ targetId: 2, requestId: 'req-2' }).accepted, true);
  workflow.onVisionResult({ targets: [{ stableId: 2 }] });

  assert.deepEqual(alignmentStarts, [{ targetId: 2, requestId: 'req-2' }]);
  assert.equal(visionInputs[0][0].stableId, 2);
  assert.equal(graspPlans[0].schema, 'fixture-plan');
  assert.equal(robotMessages.some(message => message.cmd === 'closed_loop_pick'), false);
  assert.equal(cameraMessages[0].stable_id, 2);
  assert.deepEqual(cameraMessages.at(-1), {
    type: 'release_bottle', request_id: 'req-2',
  });
  assert.equal(finishes.length, 0);
  cameraBridge.emit('selection_release_status', {
    type: 'selection_release_status', request_id: 'req-2', status: 'released',
  });
  assert.equal(finishes[0].ok, true);
  assert.equal(finishes[0].releaseSucceeded, true);
  assert.equal(typeof alignDependencies.startGrasp, 'function');
  assert.deepEqual(alignDependencies.graspOffsetBaseM, [0.0475, 0.01, 0]);
  assert.equal(typeof graspDependencies.onStatus, 'function');
  workflow.onRobotEvent({
    type: 'robot_state', poseFrame: 'robot_flange',
    flangePositionM: [0.4, 0, 0.2], flangeEulerRad: [0, 0, 0],
    jointsDeg: [0, 1, 2, 3, 4, 5], velocitiesDegS: [0, 0, 0, 0, 0, 0],
    stationary: true, observedMonotonicNs: 1000,
  });
  assert.deepEqual(forwardedArmStates.at(-1), [
    [0.4, 0, 0.2], [0, 0, 0], [0, 1, 2, 3, 4, 5],
    [0, 0, 0, 0, 0, 0], true, 1000,
  ]);
});

test('workflow stop sends one low-level software stop command', () => {
  const robotMessages = [];
  let observedMonotonicNs = 100;
  let stateSequence = 10;
  let producerMonotonicNs = 1000;
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      stopProofMode: 'fresh_state_boundary',
      send(message) { robotMessages.push(message); return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange', flangePositionM: [0.3, 0, 0.18],
        jointsDeg: [...HOME],
        observedMonotonicNs,
        stateSequence, producerMonotonicNs,
      }; },
    },
    config: homeConfig(),
    stopIdFactory: () => 'stop-req-2',
    createAlignmentController: dependencies => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      cancel(reason) {
        dependencies.onStatus({ phase: 'aborted', reason });
        return { accepted: true };
      },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
    }),
  });

  workflow.start({ targetId: 2, requestId: 'req-stop-2' });
  assert.deepEqual(workflow.cancel('operator_stop'), {
    accepted: true, reason: 'stop_requested', stopRequestId: 'stop-req-2',
  });
  assert.deepEqual(robotMessages, [{
    cmd: 'software_stop', source: 'workflow:cancel', reason: 'operator_stop',
    request_id: 'stop-req-2',
  }]);
  assert.equal(workflow.snapshot().active, true);
  workflow.onRobotEvent({
    type: 'command_complete', command: 'software_stop',
    request_id: 'stop-req-2', stopped: true,
    applied_state_sequence: 11, applied_producer_monotonic_ns: 1001,
  });
  assert.equal(workflow.snapshot().active, true);
  observedMonotonicNs = 101;
  workflow.onRobotEvent({
    type: 'robot_state', connected: true, stationary: true,
    stateFresh: true, observedMonotonicNs, stateSequence, producerMonotonicNs,
  });
  assert.equal(workflow.snapshot().active, true);
  stateSequence = 11;
  producerMonotonicNs = 1001;
  workflow.onRobotEvent({
    type: 'robot_state', connected: true, stationary: true,
    stateFresh: true, observedMonotonicNs, stateSequence, producerMonotonicNs,
  });
  assert.equal(workflow.snapshot().active, true);
  observedMonotonicNs = 102;
  stateSequence = 12;
  producerMonotonicNs = 1002;
  workflow.onRobotEvent({
    type: 'robot_state', connected: true, stationary: true,
    stateFresh: true, observedMonotonicNs, stateSequence, producerMonotonicNs,
  });
  assert.equal(workflow.snapshot().active, false);
});

test('cleanup acknowledgement finishes cancellation without claiming depower', () => {
  const finishes = [];
  const robotMessages = [];
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      stopProofMode: 'cleanup_ack_only',
      send(message) { robotMessages.push(message); return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        poseFrame: 'robot_flange', flangePositionM: [0.3, 0, 0.18],
        jointsDeg: [...HOME],
      }; },
    },
    config: homeConfig(),
    stopIdFactory: () => 'depowered-stop',
    createAlignmentController: dependencies => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      cancel(reason) { dependencies.onStatus({ phase: 'aborted', reason }); },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
    }),
    onFinish: result => finishes.push(result),
  });
  workflow.start({ targetId: 2, requestId: 'depowered-request' });
  workflow.cancel('operator_stop');

  const result = workflow.onRobotEvent({
    type: 'command_complete', command: 'software_stop',
    request_id: 'depowered-stop', cleanupAcknowledged: true,
    cleanupConfirmationMode: 'vendor_cleanup_returned',
    controlReleased: true, depowerIndependentlyConfirmed: false,
    stopped: false, depowered: false,
  });

  assert.deepEqual(result, { handled: true, accepted: true, reason: 'operator_stop' });
  assert.equal(finishes.at(-1).reason, 'operator_stop');
  assert.equal(workflow.snapshot().active, false);
  assert.equal(robotMessages.at(-1).cmd, 'software_stop');
});

test('cleanup stop mode never accepts a completion without cleanup receipt', () => {
  const finishes = [];
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      stopProofMode: 'cleanup_ack_only',
      send() { return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        jointsDeg: [...HOME],
      }; },
    },
    config: homeConfig(),
    stopIdFactory: () => 'unproved-stop',
    createAlignmentController: () => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      cancel() { return { accepted: true }; },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
    }),
    onFinish: result => finishes.push(result),
  });
  workflow.start({ targetId: 2, requestId: 'unproved-request' });
  workflow.cancel('operator_stop');

  workflow.onRobotEvent({
    type: 'command_complete', command: 'software_stop',
    request_id: 'unproved-stop', cleanupAcknowledged: false,
    cleanupConfirmationMode: 'vendor_cleanup_returned',
    controlReleased: true, depowerIndependentlyConfirmed: false,
  });

  assert.equal(finishes.at(-1).reason, 'software_stop_not_confirmed');
});

test('workflow never reports stop accepted when software stop transport failed', () => {
  const finishes = [];
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      send() { return false; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange', flangePositionM: [0.3, 0, 0.18],
        jointsDeg: [...HOME],
      }; },
    },
    config: homeConfig(),
    stopIdFactory: () => 'stop-failed',
    createAlignmentController: dependencies => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      cancel(reason) {
        dependencies.onStatus({ phase: 'aborted', reason });
        return { accepted: true };
      },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
    }),
    onFinish: result => finishes.push(result),
  });

  workflow.start({ targetId: 2, requestId: 'req-stop-failure' });
  assert.deepEqual(workflow.cancel('operator_stop'), {
    accepted: false, reason: 'software_stop_transport_unavailable',
  });
  assert.equal(finishes.at(-1).reason, 'software_stop_transport_unavailable');
});

test('workflow timeout sends software stop before finishing', async () => {
  const robotMessages = [];
  const finishes = [];
  let observedMonotonicNs = 100;
  let stateSequence = 10;
  let producerMonotonicNs = 1000;
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    robotClient: {
      stopProofMode: 'fresh_state_boundary',
      send(message) { robotMessages.push(message); return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange', flangePositionM: [0.3, 0, 0.18],
        jointsDeg: [...HOME],
        observedMonotonicNs,
        stateSequence, producerMonotonicNs,
      }; },
    },
    config: homeConfig(),
    workflowTimeoutMs: 10,
    stopIdFactory: () => 'stop-timeout',
    createAlignmentController: dependencies => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      cancel(reason) {
        dependencies.onStatus({ phase: 'aborted', reason });
        return { accepted: true };
      },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
    }),
    onFinish: result => finishes.push(result),
  });

  workflow.start({ targetId: 2, requestId: 'req-timeout' });
  await new Promise(resolve => setTimeout(resolve, 25));

  assert.equal(robotMessages.at(-1).cmd, 'software_stop');
  assert.equal(finishes.length, 0);
  workflow.onRobotEvent({
    type: 'command_complete', command: 'software_stop',
    request_id: 'stop-timeout', stopped: true,
    applied_state_sequence: 10, applied_producer_monotonic_ns: 1000,
  });
  assert.equal(finishes.length, 0);
  observedMonotonicNs = 101;
  stateSequence = 11;
  producerMonotonicNs = 1001;
  workflow.onRobotEvent({
    type: 'robot_state', connected: true, stationary: true,
    stateFresh: true, observedMonotonicNs, stateSequence, producerMonotonicNs,
  });
  assert.equal(finishes.at(-1).reason, 'workflow_timeout');
});

test('workflow cannot report success when target reservation release failed', () => {
  const finishes = [];
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(message => message.type !== 'release_bottle'),
    robotClient: {
      send() { return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange', flangePositionM: [0.3, 0, 0.18],
        jointsDeg: [...HOME],
      }; },
    },
    config: homeConfig(),
    planBuilder: handoff => ({ ...handoff, schema: 'fixture-plan' }),
    createGraspController: dependencies => ({
      active: false,
      start() {
        dependencies.onStatus({ phase: 'complete' });
        return { accepted: true };
      },
      onRobotEvent() { return { handled: false }; },
      cancel() { return { accepted: true }; },
    }),
    createAlignmentController: dependencies => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      onVisionTargets() {
        return dependencies.startGrasp({
          stableId: 2, requestId: 'req-release-failed',
          evidenceId: `sha256:${'a'.repeat(64)}`,
        });
      },
      onRobotEvent() { return { handled: false }; },
      cancel() { return { accepted: true }; },
    }),
    onFinish: result => finishes.push(result),
  });

  workflow.start({ targetId: 2, requestId: 'req-release-failed' });
  workflow.onVisionResult({ targets: [] });

  assert.equal(finishes.at(-1).ok, false);
  assert.equal(finishes.at(-1).releaseSucceeded, false);
  assert.equal(finishes.at(-1).cleanupReason, 'vision_release_transport_unavailable');
});

test('workflow stops when runtime artifact snapshot changes during a request', () => {
  const robotMessages = [];
  const runtime = {
    camera_serial: 'camera', registration_id: 'registration', camera_mount_id: 'mount',
    vision_config_id: `sha256:${'a'.repeat(64)}`,
    calibration_id: `sha256:${'b'.repeat(64)}`,
    calibration_approved: true,
    model_provenance: {
      vision_config_id: `sha256:${'a'.repeat(64)}`,
      camera_registration_id: 'registration', camera_mount_id: 'mount',
      grounding_model: 'debug/grounding', grounding_revision: '1'.repeat(40),
      grounding_weights_sha256: `sha256:${'c'.repeat(64)}`,
      sam_model: 'debug/sam', sam_revision: '2'.repeat(40),
      sam_weights_sha256: `sha256:${'d'.repeat(64)}`,
    },
  };
  const workflow = new WorkflowClient({
    cameraBridge: acknowledgingCamera(),
    runtimeEvidence: () => runtime,
    approvedRuntimeEvidence: structuredClone(runtime),
    robotClient: {
      send(message) { robotMessages.push(message); return true; },
      getRobotState() { return {
        connected: true, healthy: true, stateFresh: true, stationary: true,
        moving: false, poseFrame: 'robot_flange',
        flangePositionM: [0.3, 0, 0.18], gripperWidthM: 0.08,
        jointsDeg: [...HOME],
        observedMonotonicNs: 100, stateSequence: 10, producerMonotonicNs: 1000,
      }; },
    },
    config: homeConfig(),
    stopIdFactory: () => 'runtime-stop',
    createAlignmentController: () => ({
      active: true,
      start() { return { accepted: true, phase: 'acquiring' }; },
      onVisionTargets() { return { handled: false }; },
      onRobotEvent() { return { handled: false }; },
      cancel() { return { accepted: true }; },
    }),
  });
  assert.equal(workflow.start({ targetId: 2, requestId: 'runtime-req' }).accepted, true);
  runtime.calibration_id = `sha256:${'e'.repeat(64)}`;

  const result = workflow.onVisionResult({ targets: [] });

  assert.equal(result.reason, 'stop_requested');
  assert.equal(robotMessages.at(-1).cmd, 'software_stop');
});
