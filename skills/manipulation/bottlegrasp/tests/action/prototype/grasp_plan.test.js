'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { buildPrototypeGraspPlan } = require('../../../src/thirdhand_va/action/prototype/grasp_plan');

function input() {
  return { requestId: 'trial-1', target: { positionM: [0.3, -0.2, 0.1], eulerRad: [0, 0, 0] },
    widthM: 0.04, flangeToGrip: [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
    pregraspOffsetM: 0.1, liftDistanceM: 0.05, linearSpeedMps: 0.02 };
}

test('builds an immutable pregrasp approach grip and lift plan', () => {
  const source = input();
  const plan = buildPrototypeGraspPlan(source);
  assert.deepEqual(plan.steps.map(step => step.phase), ['pregrasp','approach','grip','lift']);
  assert.deepEqual(plan.steps.map(step => step.command.position),
    [[0.3,-0.2,0.2],[0.3,-0.2,0.1],0,[0.3,-0.2,0.15]]);
  assert.equal(plan.steps[1].command.time_sec, 5);
  assert.equal(plan.steps[3].command.time_sec, 2.5);
  assert.ok(Object.isFrozen(plan));
  assert.ok(Object.isFrozen(plan.steps[0].command.position));
  source.target.positionM[0] = 9;
  assert.equal(plan.steps[1].command.position[0], 0.3);
});

test('converts the requested grip pose into a flange pose', () => {
  const source = input();
  source.target.eulerRad = [0,0,Math.PI/2];
  source.flangeToGrip[0][3] = 0.02;
  const plan = buildPrototypeGraspPlan(source);
  assert.deepEqual(plan.steps[1].command.position, [0.3,-0.22,0.1]);
  assert.ok(Math.abs(plan.steps[1].command.euler[2] - Math.PI/2) < 1e-12);
});

test('rejects malformed geometry and positive motion inputs', () => {
  for (const field of ['widthM','pregraspOffsetM','liftDistanceM','linearSpeedMps']) {
    for (const value of [0,-1,NaN,Infinity,'0.1']) {
      const source = input(); source[field] = value;
      assert.throws(() => buildPrototypeGraspPlan(source),
        { message: field === 'widthM' ? 'prototype_width_invalid' : 'prototype_motion_invalid' });
    }
  }
  for (const field of ['positionM','eulerRad']) {
    for (const value of [[1,2], [1,2,NaN], [1,2,Infinity], null, new Array(3)]) {
      const source = input(); source.target[field] = value;
      assert.throws(() => buildPrototypeGraspPlan(source), {message:'prototype_target_invalid'});
    }
  }
  for (const requestId of ['',null,42]) {
    assert.throws(() => buildPrototypeGraspPlan({...input(),requestId}),
      {message:'prototype_request_id_invalid'});
  }
});

test('rejects reflected aliased and malformed transforms', () => {
  const row = [1,0,0,0];
  for (const matrix of [[], [row,row,[0,0,1,0],[0,0,0,1]],
    [[-1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]]) {
    assert.throws(() => buildPrototypeGraspPlan({...input(),flangeToGrip:matrix}), /grip_transform/);
  }
});

test('rejects finite inputs that overflow generated waypoints or durations', () => {
  assert.throws(() => buildPrototypeGraspPlan({...input(),
    target:{positionM:[0,0,1e308],eulerRad:[0,0,0]}, liftDistanceM:1e308}),
  /prototype_motion_invalid/);
  assert.throws(() => buildPrototypeGraspPlan({...input(),linearSpeedMps:Number.MIN_VALUE}),
    /prototype_motion_invalid/);
});

module.exports = { input };
