'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { OperatorController } = require(
  '../../../src/thirdhand_va/action/operator/controller'
);

test('operator owns one idempotent request-bound stable-ID workflow', () => {
  const starts = [];
  let finish;
  const controller = new OperatorController({
    createWorkflow({ onFinish }) {
      finish = onFinish;
      return {
        start(request) { starts.push(request); return { accepted: true }; },
        cancel() { return { accepted: true }; },
      };
    },
  });
  const request = { targetId: 2, requestId: 'req-2' };

  assert.deepEqual(controller.start(request), {
    accepted: true, duplicate: false, targetId: 2, requestId: 'req-2',
  });
  assert.equal(controller.start(request).duplicate, true);
  assert.equal(controller.start({ targetId: 3, requestId: 'req-3' }).reason,
    'workflow_active');
  assert.deepEqual(starts, [request]);
  finish({ ok: true, targetId: 2, requestId: 'req-2' });
  assert.equal(controller.snapshot().active, false);
});

test('operator rejects invalid stable ID and request ID', () => {
  const controller = new OperatorController({
    createWorkflow() { throw new Error('must not run'); },
  });
  assert.equal(controller.start({ targetId: 0, requestId: 'req' }).reason,
    'target_id_invalid');
  assert.equal(controller.start({ targetId: 2, requestId: '' }).reason,
    'request_id_invalid');
});
