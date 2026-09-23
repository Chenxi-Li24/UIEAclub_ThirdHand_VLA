'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { ActiveDepthCoordinator, TERMINAL_PHASES } = require('../../../apps/web/src/active-depth/coordinator');

const mount = {
  matrix_4x4: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
  camera_mount_id: 'mount-1', registration_id: 'registration-1',
};
const robotState = {
  observedAtMs: Date.now(), stateName: 'IDLE', moving: false,
  jointsDeg: [0,0,0,0,0,0],
  jointLimitsDeg: [[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],
};

function frame(frameId, { depth = false, stableId = 2, pixel = [500,300] } = {}) {
  return {
    observation: {
      frameId, observedAtMs: Date.now(), selectedStableId: stableId,
      evidence_id: `sha256:${String(frameId).padStart(64, '0')}`,
      motion_epoch: 0,
      targets: [{
        stable_id: stableId, centroid_xy: pixel, track_state: 'confirmed',
        depth_valid: depth, camera_xyz_m: depth ? [0.01, 0.02, 0.4] : null,
      }],
    },
    runtimeEvidence: { camera_mount_id: 'mount-1', registration_id: 'registration-1' },
  };
}

function fakeVision(frames) {
  return {
    calls: 0,
    async snapshot() {
      this.calls += 1;
      if (!frames.length) throw Object.assign(new Error('no fixture frame'), { code: 'fixture_exhausted' });
      return frames.shift();
    },
  };
}

function waitFor(predicate, timeoutMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const check = () => {
      if (predicate()) return resolve();
      if (Date.now() >= deadline) return reject(new Error('condition timeout'));
      setTimeout(check, 5);
    };
    check();
  });
}

function harness({ frames, planner, execution, robot = {} } = {}) {
  const vision = fakeVision(frames || []);
  const sent = [];
  const executionClient = execution || {
    async execute(primitive) {
      sent.push(primitive);
      return { status: 'completed', code: 'target_reached', primitiveId: primitive.primitiveId };
    },
    async stop() { return { status: 'stop_requested' }; },
    close() {},
  };
  const coordinator = new ActiveDepthCoordinator({
    visionClient: vision, executionClient,
    getRobotState: () => ({ ...robotState, ...robot, observedAtMs: Date.now() }),
    mount, pollIntervalMs: 0,
    planStep: planner || (() => ({ ok: false, reason: 'not_reachable' })),
  });
  return { coordinator, vision, sent, executionClient };
}

test('explicit start requires three increasing centered depth-valid frames and sends no motion', async (t) => {
  const centered = { depth: true, pixel: [315.5, 234] };
  const h = harness({ frames: [frame(41, centered), frame(42, centered), frame(43, centered)] });
  t.after(() => h.coordinator.close());
  const started = await h.coordinator.start(2);
  assert.equal(started.phase, 'observing');
  await waitFor(() => h.coordinator.status().phase === 'depth_acquired');
  assert.equal(h.coordinator.status().depthValidFrames, 3);
  assert.equal(h.sent.length, 0);
});

test('coordinator executes wrist before planner-authorized arm fallback', async (t) => {
  const plans = [
    { ok: true, tier: 'wrist', wristExhausted: false, targetJointsDeg: [0,0,0,0,1,0],
      predictedPixel: [450,280], angularErrorRad: 0.2, initialAngularErrorRad: 0.3,
      cameraShiftM: 0, cameraCumulativeM: 0, jointDeltasDeg: [0,0,0,0,1,0] },
    { ok: true, tier: 'arm_fallback', wristExhausted: true, targetJointsDeg: [0.5,0,0,0,0,0],
      predictedPixel: [400,260], angularErrorRad: 0.1, initialAngularErrorRad: 0.2,
      cameraShiftM: 0, cameraCumulativeM: 0, jointDeltasDeg: [0.5,0,0,0,0,0] },
  ];
  const h = harness({
    frames: [frame(1, { pixel: [520,310] }), frame(2, { pixel: [460,285] }),
      frame(3, { depth: true, pixel: [320,236] }), frame(4, { depth: true, pixel: [318,235] }),
      frame(5, { depth: true, pixel: [316,234] })],
    planner: () => plans.shift() || { ok: false, reason: 'unexpected_plan' },
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => h.coordinator.status().phase === 'depth_acquired');
  assert.deepEqual(h.sent.map(item => item.parameters.tier), ['wrist', 'arm_fallback']);
  assert.equal(h.sent[1].parameters.wristExhausted, true);
});

test('valid depth outside the center keeps aligning until three centered frames', async (t) => {
  const plans = [{
    ok: true, tier: 'wrist', wristExhausted: false, targetJointsDeg: [0,0,0,0,4,0],
    predictedPixel: [320,235], angularErrorRad: 0.01, initialAngularErrorRad: 0.2,
    cameraShiftM: 0.004, cameraCumulativeM: 0.004, jointDeltasDeg: [0,0,0,0,4,0],
  }];
  const h = harness({
    frames: [
      frame(20, { depth: true, pixel: [416,195] }),
      frame(21, { depth: true, pixel: [320,235] }),
      frame(22, { depth: true, pixel: [318,234] }),
      frame(23, { depth: true, pixel: [316,234] }),
    ],
    planner: () => plans.shift() || { ok: false, reason: 'unexpected_plan' },
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => h.coordinator.status().phase === 'depth_acquired');
  assert.equal(h.sent.length, 1);
  assert.equal(h.coordinator.status().depthValidFrames, 3);
});

test('one noisy non-improving frame is corrected instead of ending the session', async (t) => {
  const plans = [
    { ok: true, tier: 'wrist', wristExhausted: false, targetJointsDeg: [0,0,0,0,4,0],
      predictedPixel: [480,290], angularErrorRad: 0.2, initialAngularErrorRad: 0.3,
      cameraShiftM: 0.004, cameraCumulativeM: 0.004, jointDeltasDeg: [0,0,0,0,4,0] },
    { ok: true, tier: 'wrist', wristExhausted: false, targetJointsDeg: [0,0,0,4,0,0],
      predictedPixel: [320,235], angularErrorRad: 0.01, initialAngularErrorRad: 0.3,
      cameraShiftM: 0.004, cameraCumulativeM: 0.008, jointDeltasDeg: [0,0,0,4,0,0] },
  ];
  const h = harness({
    frames: [
      frame(30, { pixel: [500,300] }), frame(31, { pixel: [501,300] }),
      frame(32, { depth: true, pixel: [320,235] }),
      frame(33, { depth: true, pixel: [318,234] }),
      frame(34, { depth: true, pixel: [316,234] }),
    ],
    planner: () => plans.shift() || { ok: false, reason: 'unexpected_plan' },
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => TERMINAL_PHASES.has(h.coordinator.status().phase));
  assert.equal(h.coordinator.status().phase, 'depth_acquired');
  assert.equal(h.sent.length, 2);
});

test('two stagnant wrist observations force the lower-priority arm fallback', async (t) => {
  const forceArmFallbackValues = [];
  const h = harness({
    frames: [
      frame(40, { pixel: [500,300] }), frame(41, { pixel: [501,300] }),
      frame(42, { pixel: [502,300] }),
      frame(43, { depth: true, pixel: [320,235] }),
      frame(44, { depth: true, pixel: [318,234] }),
      frame(45, { depth: true, pixel: [316,234] }),
    ],
    planner: options => {
      forceArmFallbackValues.push(options.forceArmFallback);
      const arm = options.forceArmFallback;
      return {
        ok: true, tier: arm ? 'arm_fallback' : 'wrist', wristExhausted: arm,
        targetJointsDeg: arm ? [0.5,0,0,0,0,0] : [0,0,0,0,0.5,0],
        predictedPixel: arm ? [320,235] : [499,300],
        angularErrorRad: arm ? 0.01 : 0.2, initialAngularErrorRad: 0.3,
        cameraShiftM: 0, cameraCumulativeM: 0,
        jointDeltasDeg: arm ? [0.5,0,0,0,0,0] : [0,0,0,0,0.5,0],
      };
    },
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => TERMINAL_PHASES.has(h.coordinator.status().phase));
  assert.equal(h.coordinator.status().phase, 'depth_acquired');
  assert.deepEqual(forceArmFallbackValues, [false, false, true]);
  assert.deepEqual(h.sent.map(item => item.parameters.tier), ['wrist', 'wrist', 'arm_fallback']);
});

test('duplicate frames are ignored until three increasing depth frames arrive', async (t) => {
  const duplicate = harness({ frames: [
    frame(10, { depth: true, pixel: [315.5,234] }), frame(10, { depth: true, pixel: [315.5,234] }),
    frame(11, { depth: true, pixel: [315.5,234] }), frame(12, { depth: true, pixel: [315.5,234] }),
  ] });
  t.after(() => duplicate.coordinator.close());
  await duplicate.coordinator.start(2);
  await waitFor(() => duplicate.coordinator.status().phase === 'depth_acquired');
  assert.equal(duplicate.coordinator.status().depthValidFrames, 3);
  assert.equal(duplicate.sent.length, 0);
});

test('out-of-order frames are ignored and target switches fail without motion', async (t) => {
  const regressed = harness({ frames: [
    frame(10, { depth: true, pixel: [315.5,234] }), frame(9, { depth: true, pixel: [315.5,234] }),
    frame(11, { depth: true, pixel: [315.5,234] }), frame(12, { depth: true, pixel: [315.5,234] }),
  ] });
  t.after(() => regressed.coordinator.close());
  await regressed.coordinator.start(2);
  await waitFor(() => regressed.coordinator.status().phase === 'depth_acquired');
  assert.equal(regressed.coordinator.status().depthValidFrames, 3);
  assert.equal(regressed.sent.length, 0);

  const switched = harness({ frames: [frame(11, { stableId: 3 })] });
  t.after(() => switched.coordinator.close());
  await switched.coordinator.start(2);
  await waitFor(() => switched.coordinator.status().phase === 'failed');
  assert.equal(switched.coordinator.status().reason, 'target_switched');
});

test('operator stop during an in-flight step requests protected stop and stays terminal', async (t) => {
  let resolveExecution;
  const stops = [];
  const execution = {
    execute() { return new Promise(resolve => { resolveExecution = resolve; }); },
    async stop(sessionId) { stops.push(sessionId); return { status: 'interrupted' }; },
    close() {},
  };
  const h = harness({
    frames: [frame(1)], execution,
    planner: () => ({ ok: true, tier: 'wrist', wristExhausted: false,
      targetJointsDeg: [0,0,0,0,1,0], predictedPixel: [450,280],
      angularErrorRad: 0.2, initialAngularErrorRad: 0.3,
      cameraShiftM: 0, cameraCumulativeM: 0, jointDeltasDeg: [0,0,0,0,1,0] }),
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => h.coordinator.status().phase === 'moving');
  const sessionId = h.coordinator.status().sessionId;
  await h.coordinator.stop(sessionId);
  assert.deepEqual(stops, [sessionId]);
  assert.equal(h.coordinator.status().phase, 'stopped');
  resolveExecution({ status: 'interrupted', code: 'operator_stop' });
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(h.coordinator.status().phase, 'stopped');
});

test('operator stop becomes uncertain unless protected execution confirms interruption', async (t) => {
  let resolveExecution;
  const execution = {
    execute() { return new Promise(resolve => { resolveExecution = resolve; }); },
    async stop() { return { status: 'uncertain', code: 'stop_timeout' }; },
    close() {},
  };
  const h = harness({
    frames: [frame(1)], execution,
    planner: () => ({ ok: true, tier: 'wrist', wristExhausted: false,
      targetJointsDeg: [0,0,0,0,1,0], predictedPixel: [450,280],
      angularErrorRad: 0.2, initialAngularErrorRad: 0.3,
      cameraShiftM: 0, cameraCumulativeM: 0, jointDeltasDeg: [0,0,0,0,1,0] }),
  });
  t.after(() => h.coordinator.close());
  await h.coordinator.start(2);
  await waitFor(() => h.coordinator.status().phase === 'moving');
  await h.coordinator.stop(h.coordinator.status().sessionId);
  assert.equal(h.coordinator.status().phase, 'uncertain');
  assert.equal(h.coordinator.status().reason, 'stop_timeout');
  resolveExecution({ status: 'interrupted', code: 'operator_stop' });
});

test('coordinator rejects disconnected robot state and a lost selected target', async (t) => {
  const disconnected = harness({ frames: [], robot: { connected: false, stateFresh: true } });
  t.after(() => disconnected.coordinator.close());
  await assert.rejects(disconnected.coordinator.start(2), error => error.code === 'robot_not_stationary');

  const lostFrame = frame(1);
  lostFrame.observation.targets[0].track_state = 'lost';
  const lost = harness({ frames: [lostFrame] });
  t.after(() => lost.coordinator.close());
  await lost.coordinator.start(2);
  await waitFor(() => lost.coordinator.status().phase === 'failed');
  assert.equal(lost.coordinator.status().reason, 'target_not_confirmed');
  assert.equal(lost.sent.length, 0);
});
