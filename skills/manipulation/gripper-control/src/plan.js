'use strict';

const { randomUUID } = require('node:crypto');
const { digestPlan } = require('../../../../platform/authorization/src/canonical-json');

const GRIPPER_INTENTS = Object.freeze({
  'gripper.open': 100,
  'gripper.close': 0,
});

function codedError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function createGripperProposal(candidate, {
  clock = Date.now,
  idFactory = randomUUID,
  readiness,
  proposalLifetimeMs = 30_000,
} = {}) {
  if (!candidate || !(candidate.intent in GRIPPER_INTENTS)) {
    throw codedError('unsupported_intent', 'Only gripper.open and gripper.close are supported');
  }
  for (const field of ['candidateId', 'traceId', 'source', 'transcript']) {
    if (typeof candidate[field] !== 'string' || candidate[field].length === 0) {
      throw codedError('candidate_invalid', `Candidate ${field} is required`);
    }
  }
  const positionPercent = GRIPPER_INTENTS[candidate.intent];
  const plan = {
    schema: 'thirdhand.task-plan.v1',
    taskId: idFactory(),
    planId: idFactory(),
    revision: 1,
    targetRef: 'robot:gripper',
    risk: 'physical-motion',
    steps: [{
      id: idFactory(),
      skillId: 'manipulation.gripper-control',
      operation: 'gripper.set',
      parameters: { positionPercent, tolerancePercent: 2, timeoutMs: 3000 },
    }],
    risks: ['夹爪运动可能造成夹伤或挤压。'],
  };
  return {
    schema: 'thirdhand.plan-proposal.v1',
    proposalId: idFactory(),
    candidateId: candidate.candidateId,
    traceId: candidate.traceId,
    planDigest: digestPlan(plan),
    expiresAt: new Date(clock() + proposalLifetimeMs).toISOString(),
    plan,
    readiness: structuredClone(readiness),
    risks: [...plan.risks],
  };
}

module.exports = { GRIPPER_INTENTS, createGripperProposal };
