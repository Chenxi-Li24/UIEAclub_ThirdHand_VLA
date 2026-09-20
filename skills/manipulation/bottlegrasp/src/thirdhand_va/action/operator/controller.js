'use strict';

class OperatorController {
  constructor({ createWorkflow, statusStore = null } = {}) {
    if (typeof createWorkflow !== 'function' ||
        !(statusStore === null || typeof statusStore.write === 'function')) {
      throw new TypeError('operator controller dependencies are invalid');
    }
    this.createWorkflow = createWorkflow;
    this.statusStore = statusStore;
    this.workflow = null;
    this.activeRequest = null;
    this.lastResult = null;
  }

  snapshot() {
    const workflowStatus = this.workflow?.snapshot?.() ?? null;
    return Object.freeze({
      schema: 'thirdhand.va.status.v1',
      active: this.workflow !== null,
      target_id: this.activeRequest?.targetId ?? null,
      request_id: this.activeRequest?.requestId ?? null,
      workflow: workflowStatus,
      last_result: this.lastResult,
    });
  }

  start({ targetId, requestId } = {}) {
    if (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5) {
      return { accepted: false, reason: 'target_id_invalid' };
    }
    if (typeof requestId !== 'string' || !requestId) {
      return { accepted: false, reason: 'request_id_invalid' };
    }
    if (this.workflow !== null) {
      if (this.activeRequest.targetId === targetId &&
          this.activeRequest.requestId === requestId) {
        return { accepted: true, duplicate: true, targetId, requestId };
      }
      return { accepted: false, reason: 'workflow_active' };
    }
    let workflow;
    workflow = this.createWorkflow({
      targetId,
      requestId,
      onFinish: result => {
        if (this.workflow === workflow) {
          this.workflow = null;
          this.activeRequest = null;
        }
        this.lastResult = result;
        this._write();
      },
    });
    if (!workflow || typeof workflow.start !== 'function' ||
        typeof workflow.cancel !== 'function') {
      return { accepted: false, reason: 'workflow_invalid' };
    }
    this.workflow = workflow;
    this.activeRequest = { targetId, requestId };
    const result = workflow.start({ targetId, requestId });
    if (result?.accepted !== true) {
      this.workflow = null;
      this.activeRequest = null;
      this.lastResult = result;
      this._write();
      return result;
    }
    this._write();
    return { accepted: true, duplicate: false, targetId, requestId };
  }

  stop(reason = 'operator_stop') {
    if (this.workflow === null) return { accepted: true, duplicate: true };
    const result = this.workflow.cancel(reason);
    this._write();
    return result;
  }

  _write() {
    this.statusStore?.write(this.snapshot());
  }
}

module.exports = { OperatorController };
