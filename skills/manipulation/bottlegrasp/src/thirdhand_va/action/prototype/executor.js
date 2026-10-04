'use strict';

const { PrototypeSimulator } = require('./simulator');
const { isPrototypePlan } = require('./grasp_plan');

class PrototypeGraspExecutor {
  constructor({ simulator } = {}) {
    if (!(simulator instanceof PrototypeSimulator)) throw new TypeError('prototype_simulator_required');
    this.simulator = simulator;
    this.plan = null;
    this.index = 0;
    this.status = 'idle';
    this.reason = null;
    this.inFlightRequestId = null;
    this.completed = new Set();
  }
  start(plan) {
    if (this.status !== 'idle') return {accepted:false,reason:'prototype_session_active'};
    if (!isPrototypePlan(plan)) throw new TypeError('prototype_plan_invalid');
    this.plan = plan;
    this.status = 'running';
    this._send();
    return {accepted:this.status !== 'failed',...this.snapshot()};
  }
  ack(event = {}) {
    if (!event || event.type !== 'command_complete') return {handled:false};
    if (this.completed.has(event.request_id)) return {handled:true,duplicate:true};
    if (this.status !== 'running' || event.request_id !== this.inFlightRequestId) return {handled:false};
    this.inFlightRequestId = null;
    if (event.reached !== true) {
      this.status = 'failed'; this.reason = 'prototype_completion_failed';
      return {handled:true,...this.snapshot()};
    }
    this.completed.add(event.request_id);
    this.index += 1;
    if (this.index === this.plan.steps.length) this.status = 'complete';
    else this._send();
    return {handled:true,...this.snapshot()};
  }
  _send() {
    const step = this.plan.steps[this.index];
    this.inFlightRequestId = `${this.plan.requestId}:${step.phase}`;
    const command = {...step.command,request_id:this.inFlightRequestId,
      source:'prototype_grasp_validation'};
    try {
      if (this.simulator.send(command) === true) return;
    } catch {
      // A simulator callback failure is terminal for this run.
    }
    this.status = 'failed'; this.reason = 'prototype_send_failed'; this.inFlightRequestId = null;
  }
  snapshot() {
    return Object.freeze({status:this.status,reason:this.reason,
      phase:this.plan?.steps[this.index]?.phase ?? null,
      completedPhases:this.completed.size,inFlightRequestId:this.inFlightRequestId});
  }
}

module.exports = { PrototypeGraspExecutor };
