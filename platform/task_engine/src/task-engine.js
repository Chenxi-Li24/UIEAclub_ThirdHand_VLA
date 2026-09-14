'use strict';

const { EventEmitter } = require('node:events');
const { codedError } = require('../../authorization/src/authorization-store');
const { createContractValidator } = require('../../contracts/src/validator');

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  Object.freeze(value);
  for (const child of Object.values(value)) deepFreeze(child);
  return value;
}

function readinessOk(value) {
  return Boolean(value?.authorizationReady
    && value.robot?.reachable
    && value.robot?.connected
    && value.robot?.stateReady
    && value.robot?.fresh
    && !value.robot?.moving
    && value.skill?.available);
}

class TaskEngine extends EventEmitter {
  constructor({ authorizationStore, resolveSkill, readinessProvider, clock = Date.now }) {
    super();
    this.authorizationStore = authorizationStore;
    this.resolveSkill = resolveSkill;
    this.readinessProvider = readinessProvider;
    this.clock = clock;
    this.tasks = new Map();
    this.proposals = new Map();
    this.authorizationTasks = new Map();
    this.contracts = createContractValidator();
  }

  registerProposal({ proposal }) {
    if (this.proposals.has(proposal.proposalId)) throw codedError('proposal_duplicate', 'Proposal already exists');
    const immutable = deepFreeze(structuredClone(proposal));
    const task = { proposal: immutable, state: 'awaiting_authorization', authorizationId: null, result: null };
    this.proposals.set(immutable.proposalId, task);
    this.tasks.set(immutable.plan.taskId, task);
    this.emit('state', { taskId: immutable.plan.taskId, traceId: immutable.traceId, state: task.state, at: new Date(this.clock()).toISOString() });
    return immutable;
  }

  async grantAuthorization({ proposalId, planId, planRevision, planDigest }) {
    const task = this.proposals.get(proposalId);
    if (!task) throw codedError('proposal_unknown', 'Proposal does not exist');
    if (task.state !== 'awaiting_authorization') throw codedError('invalid_task_transition', 'Task is not awaiting authorization');
    const { proposal } = task;
    if (this.clock() >= Date.parse(proposal.expiresAt)) {
      task.state = 'expired';
      throw codedError('proposal_expired', 'Proposal expired');
    }
    if (proposal.plan.planId !== planId || proposal.plan.revision !== planRevision) {
      throw codedError('plan_binding_mismatch', 'Displayed plan identity changed');
    }
    if (proposal.planDigest !== planDigest) throw codedError('plan_digest_mismatch', 'Displayed plan digest changed');
    const readiness = await this.readinessProvider();
    if (!readinessOk(readiness)) throw codedError('readiness_unavailable', 'Robot or Skill is not ready');
    const operation = proposal.plan.steps[0].operation;
    const grant = this.authorizationStore.issue({
      plan: proposal.plan,
      planDigest,
      expiresAt: proposal.expiresAt,
      authorizedOperations: [operation],
    });
    task.authorizationId = grant.authorizationId;
    task.state = 'authorized';
    this.authorizationTasks.set(grant.authorizationId, task);
    this.emit('state', { taskId: proposal.plan.taskId, traceId: proposal.traceId, state: task.state, at: new Date(this.clock()).toISOString() });
    return grant;
  }

  async executeAuthorized({ authorizationId, signal }) {
    const task = this.authorizationTasks.get(authorizationId);
    if (!task) throw codedError('authorization_unknown', 'Authorization does not map to a task');
    if (task.state !== 'authorized') throw codedError('invalid_task_transition', 'Task cannot execute from its current state');
    const readiness = await this.readinessProvider();
    if (!readinessOk(readiness)) throw codedError('readiness_unavailable', 'Robot or Skill is not ready');
    const { proposal } = task;
    const step = proposal.plan.steps[0];
    const authorization = this.authorizationStore.consume({
      authorizationId,
      plan: proposal.plan,
      planDigest: proposal.planDigest,
      operation: step.operation,
    });
    task.state = 'running';
    this.emit('state', { taskId: proposal.plan.taskId, traceId: proposal.traceId, state: task.state, at: new Date(this.clock()).toISOString() });
    try {
      const worker = await this.resolveSkill(step.skillId);
      const result = await worker.execute({ plan: proposal.plan, authorization, traceId: proposal.traceId, signal });
      const validation = this.contracts.validate('thirdhand.skill-result.v1', result);
      if (!validation.ok) throw codedError('skill_result_invalid', JSON.stringify(validation.errors));
      task.result = result;
      task.state = result.status === 'completed' ? 'completed' : result.status;
      this.emit('state', { taskId: proposal.plan.taskId, traceId: proposal.traceId, state: task.state, at: new Date(this.clock()).toISOString() });
      return result;
    } catch (error) {
      task.state = error.code === 'interrupted' ? 'interrupted' : 'failed';
      throw error;
    }
  }

  interrupt(taskId, reason) {
    const task = this.tasks.get(taskId);
    if (!task || ['completed', 'failed', 'interrupted', 'expired'].includes(task.state)) return false;
    task.state = 'interrupted';
    task.result = { reason };
    if (task.authorizationId) this.authorizationStore.revoke(task.authorizationId, reason);
    return true;
  }

  getTask(taskId) {
    const task = this.tasks.get(taskId);
    return task ? { state: task.state, proposal: task.proposal, authorizationId: task.authorizationId, result: task.result } : null;
  }
}

module.exports = { TaskEngine, deepFreeze, readinessOk };
