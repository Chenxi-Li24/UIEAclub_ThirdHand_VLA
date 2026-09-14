'use strict';

const { randomUUID } = require('node:crypto');

async function execute({ plan, authorization, traceId, signal, robotClient, idFactory = randomUUID }) {
  const step = plan?.steps?.[0];
  if (!step || plan.steps.length !== 1 || step.skillId !== 'manipulation.gripper-control' || step.operation !== 'gripper.set') {
    const error = new Error('Gripper plan must contain exactly one gripper.set step');
    error.code = 'plan_invalid';
    throw error;
  }
  if (authorization.taskId !== plan.taskId
    || authorization.planId !== plan.planId
    || authorization.planRevision !== plan.revision
    || authorization.targetRef !== plan.targetRef
    || !authorization.authorizedOperations.includes('gripper.set')) {
    const error = new Error('Authorization does not match the gripper plan');
    error.code = 'authorization_stale';
    throw error;
  }
  const primitive = {
    schema: 'thirdhand.execution-primitive.v1',
    primitiveId: idFactory(),
    traceId,
    taskId: plan.taskId,
    authorizationId: authorization.authorizationId,
    planDigest: authorization.planDigest,
    operation: 'gripper.set',
    parameters: { ...step.parameters },
  };
  const response = await robotClient.execute(primitive, { signal });
  const completed = response.status === 'completed';
  const uncertain = response.status === 'uncertain';
  return {
    schema: 'thirdhand.skill-result.v1',
    taskId: plan.taskId,
    traceId,
    skillId: 'manipulation.gripper-control',
    status: completed ? 'completed' : (uncertain ? 'interrupted' : 'failed'),
    reason: {
      code: response.code || (completed ? 'target_reached' : 'robot_execution_failed'),
      message: completed ? 'Gripper reached the authorized target' : 'Robot Service did not confirm the authorized target',
      details: { robotStatus: response.status },
    },
    output: {
      requestedPercent: step.parameters.positionPercent,
      actualPercent: response.actualPercent ?? null,
      maxJointDeltaDeg: response.maxJointDeltaDeg ?? null,
    },
  };
}

module.exports = { execute };
