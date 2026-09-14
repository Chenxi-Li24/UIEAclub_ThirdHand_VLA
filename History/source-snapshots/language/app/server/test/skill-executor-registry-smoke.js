'use strict';

const assert = require('assert/strict');
const {
  PICK_SKILL,
  SkillExecutorRegistry,
  validatePickAndPlaceCandidate,
} = require('../skill-executor-registry');

function candidate(overrides = {}) {
  return {
    candidateId: 'candidate-coke-1',
    traceId: 'trace-coke-1',
    sourceText: '拿一个可乐放到 B 区',
    skill: PICK_SKILL,
    requiresConfirmation: true,
    payload: {
      params: {
        object: 'coke_bottle',
        destination: { id: 'drop_zone_b', type: 'configured_drop_zone' },
      },
    },
    ...overrides,
  };
}

assert.equal(validatePickAndPlaceCandidate(candidate()).ok, true);
assert.equal(validatePickAndPlaceCandidate(candidate({
  payload: { params: { object: 'cup', destination: { id: 'drop_zone_b', type: 'configured_drop_zone' } } },
})).ok, false);
assert.equal(validatePickAndPlaceCandidate(candidate({
  payload: { params: {
    object: 'coke_bottle',
    destination: { id: 'drop_zone_b', type: 'configured_drop_zone' },
    jointsRad: [0, 0, 0, 0, 0, 0],
  } },
})).ok, false);

const registry = new SkillExecutorRegistry();
const missing = registry.dispatch(PICK_SKILL, {
  candidate: candidate(),
  confirmation: {
    decision: 'confirmed', candidateId: 'candidate-coke-1', traceId: 'trace-coke-1',
  },
});
assert.equal(missing.accepted, false);
assert.match(missing.reason, /尚未注册/);

let received = null;
registry.register(PICK_SKILL, {
  start(request) {
    received = request;
    return { status: 'pending' };
  },
});
const dispatched = registry.dispatch(PICK_SKILL, {
  candidate: candidate(),
  confirmation: {
    decision: 'confirmed', candidateId: 'candidate-coke-1', traceId: 'trace-coke-1',
  },
  emit: () => {},
});
assert.equal(dispatched.accepted, true);
assert.equal(received.skill, PICK_SKILL);
assert.equal(received.candidate.payload.params.object, 'coke_bottle');
assert.equal('jointsRad' in received.candidate.payload.params, false);
assert.equal(received.confirmation.decision, 'confirmed');
assert.throws(() => registry.register(PICK_SKILL, { start() {} }), /已注册/);

console.log('PASS complex Skill registry is contract-bound and fail-closed');
