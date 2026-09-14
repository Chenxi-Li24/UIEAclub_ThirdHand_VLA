'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { GraspController } = require(
  '../../../src/thirdhand_va/action/grasp/grasp_controller'
);

function plan(overrides = {}) {
  return {
    schema: 'thirdhand-execution-plan-v2',
    stableId: 2,
    requestId: 'req-2',
    evidenceId: `sha256:${'a'.repeat(64)}`,
    motionEpoch: 3,
    finalApproachM: [0.40, 0.05, 0.18],
    liftM: [0.40, 0.05, 0.30],
    prePlaceM: [0.52, -0.20, 0.22],
    placeM: [0.52, -0.20, 0.10],
    retreatM: [0.52, -0.20, 0.22],
    graspEulerRad: [0.052626251, -0.083733625, 0.492493650],
    placeEulerRad: [0.001938936, -0.075722729, -1.123057982],
    homePreset: 'home',
    homeJointsDeg: [0, 15, -30, 5, 0, 0],
    homeToleranceDeg: 0.5,
    widthM: 0.06,
    contactMinWidthM: 0.008,
    contactMaxWidthM: 0.070,
    releaseMinWidthM: 0.074,
    releaseMaxWidthM: 0.080,
    timeSecByPhase: {
      final_approach: 3.334,
      lift: 4,
      transfer: 9.621,
      lower: 4,
      retreat: 4,
    },
    transferSegments: [
      { position: [0.52, -0.20, 0.22], timeSec: 9.621 },
    ],
    openPosition: 1.0,
    closePosition: 0.0,
    pathValidationId: `sha256:${'b'.repeat(64)}`,
    ...overrides,
  };
}

function harness() {
  let request = 0;
  const sent = [];
  const statuses = [];
  const controller = new GraspController({
    robotClient: { send(command) { sent.push(command); return true; } },
    getRobotState: () => ({ connected: true, healthy: true, stateFresh: true }),
    idFactory: () => `grasp-command-${++request}`,
    onStatus: status => statuses.push(status),
  });
  function complete(overrides = {}) {
    const command = sent.at(-1);
    return controller.onRobotEvent({
      type: 'command_complete',
      command: command.cmd,
      request_id: command.request_id,
      reached: command.source === 'grasp:close' ? false : true,
      actual_width_m: command.source === 'grasp:close' ? 0.040
        : command.source === 'grasp:release' ? 0.080 : undefined,
      actualJointsDeg: command.source === 'grasp:return_home'
        ? [0, 15, -30, 5, 0, 0] : undefined,
      robot_healthy: true,
      ...overrides,
    });
  }
  return { controller, sent, statuses, complete };
}

test('one accepted plan completes grasp place retreat and home', () => {
  const h = harness();

  assert.equal(h.controller.start(plan()).accepted, true);
  for (let index = 0; index < 9; index += 1) h.complete();

  assert.deepEqual(h.sent.map(command => command.source), [
    'grasp:open', 'grasp:final_approach', 'grasp:close', 'grasp:lift',
    'grasp:transfer', 'grasp:lower', 'grasp:release', 'grasp:retreat',
    'grasp:return_home',
  ]);
  assert.equal(h.controller.snapshot().phase, 'complete');
  assert.equal(h.controller.snapshot().holdingObject, false);
  assert.deepEqual(
    h.sent.filter(command => command.cmd === 'move_l')
      .map(command => command.time_sec),
    [3.334, 4, 9.621, 4, 4]
  );
  assert.deepEqual(
    h.sent.filter(command => command.cmd === 'move_l')
      .map(command => command.euler),
    [
      [0.052626251, -0.083733625, 0.492493650],
      [0.052626251, -0.083733625, 0.492493650],
      [0.001938936, -0.075722729, -1.123057982],
      [0.001938936, -0.075722729, -1.123057982],
      [0.001938936, -0.075722729, -1.123057982],
    ],
  );
});

test('controller completes every protocol-safe transfer segment before lowering', () => {
  const h = harness();
  const started = h.controller.start(plan({
    timeSecByPhase: {
      final_approach: 3.334,
      lift: 4,
      transfer: 40,
      lower: 4,
      retreat: 4,
    },
    transferSegments: [
      { position: [0.46, -0.075, 0.26], timeSec: 20 },
      { position: [0.52, -0.20, 0.22], timeSec: 20 },
    ],
  }));

  assert.equal(started.accepted, true);
  while (h.controller.active) h.complete();

  assert.deepEqual(
    h.sent.filter(command => command.source.startsWith('grasp:transfer'))
      .map(command => ({
        source: command.source,
        position: command.position,
        timeSec: command.time_sec,
      })),
    [
      {
        source: 'grasp:transfer:1of2',
        position: [0.46, -0.075, 0.26],
        timeSec: 20,
      },
      {
        source: 'grasp:transfer:2of2',
        position: [0.52, -0.20, 0.22],
        timeSec: 20,
      },
    ],
  );
  assert.equal(h.controller.snapshot().phase, 'complete');
});

test('release requires measured open width before clearing held object', () => {
  const h = harness();
  h.controller.start(plan());
  for (let index = 0; index < 6; index += 1) h.complete();

  const result = h.complete({ actual_width_m: undefined });

  assert.equal(result.phase, 'manual_recovery');
  assert.equal(result.failedPhase, 'release');
  assert.equal(h.controller.snapshot().holdingObject, true);
  assert.equal(h.sent.some(command => command.source === 'grasp:retreat'), false);
});

test('post-close failure never opens or returns home automatically', () => {
  const h = harness();
  h.controller.start(plan());
  h.complete(); // open
  h.complete(); // final approach
  h.complete(); // contact-verified close
  const lift = h.sent.at(-1);

  h.controller.onRobotEvent({
    type: 'error', command: 'move_l', request_id: lift.request_id,
  });

  assert.equal(h.controller.snapshot().reason, 'manual_recovery_required');
  assert.equal(h.controller.snapshot().holdingObject, true);
  assert.equal(h.sent.some(command => command.source === 'grasp:release'), false);
  assert.equal(h.sent.some(command => command.source === 'grasp:return_home'), false);
});

test('close must prove contact inside configured width interval', () => {
  const h = harness();
  h.controller.start(plan());
  h.complete();
  h.complete();

  const result = h.complete({ actual_width_m: 0.003 });

  assert.equal(result.reason, 'grasp_contact_not_verified');
  assert.equal(h.controller.snapshot().phase, 'manual_recovery');
  assert.equal(h.sent.some(command => command.source === 'grasp:lift'), false);
});

test('unrelated robot completion cannot advance the phase', () => {
  const h = harness();
  h.controller.start(plan());

  const result = h.controller.onRobotEvent({
    type: 'command_complete', command: 'gripper', request_id: 'other', reached: true,
  });

  assert.equal(result.handled, false);
  assert.equal(result.reason, 'request_mismatch');
  assert.equal(h.sent.length, 1);
});

test('return Home completion requires measured joints inside the approved tolerance', () => {
  const h = harness();
  h.controller.start(plan());
  for (let index = 0; index < 8; index += 1) h.complete();

  const result = h.complete({
    actualJointsDeg: [0, 15, -30, 5, 0, 0.6],
  });

  assert.equal(result.accepted, false);
  assert.equal(result.failedPhase, 'return_home');
  assert.equal(h.controller.snapshot().phase, 'manual_recovery');
  assert.equal(h.controller.snapshot().reason, 'home_not_verified');
});
