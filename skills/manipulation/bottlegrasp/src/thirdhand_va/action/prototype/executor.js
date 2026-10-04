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
    this.sending = false;
    this.pendingAck = null;
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
    if (this.sending) {
      this.pendingAck ??= {type:event.type,request_id:event.request_id,reached:event.reached};
      return {handled:true,deferred:true};
    }
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
    let sent = false;
    this.sending = true;
    try {
      sent = this.simulator.send(command) === true;
    } catch {
      // A simulator callback failure is terminal for this run.
    } finally {
      this.sending = false;
    }
    const pendingAck = this.pendingAck;
    this.pendingAck = null;
    if (sent) {
      if (pendingAck) this.ack(pendingAck);
      return;
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
