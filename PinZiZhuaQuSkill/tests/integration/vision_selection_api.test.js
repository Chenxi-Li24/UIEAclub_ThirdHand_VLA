'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const {
  createVisionSelectionHandler,
} = require('../../src/thirdhand_va/action/adapters/vision_selection_api');

function invoke(handler, body) {
  let result = null;
  handler({ body }, {
    status(code) {
      return { json(payload) { result = { code, payload }; } };
    },
  });
  return result;
}

test('voice selection reaches only the vision bridge', () => {
  const messages = [];
  const handler = createVisionSelectionHandler({
    cameraBridge: { send(message) { messages.push(message); return true; } },
    makeRequestId: () => 'generated-7',
  });

  const result = invoke(handler, { side: 'left', ordinal: 2 });

  assert.deepEqual(messages, [{
    type: 'select_bottle', side: 'left', ordinal: 2, request_id: 'generated-7',
  }]);
  assert.deepEqual(result, {
    code: 202,
    payload: {
      accepted: true,
      request_id: 'generated-7',
      selection: { side: 'left', ordinal: 2 },
      robot_control_enabled: false,
      reason: null,
    },
  });
});

test('invalid selection never reaches the vision bridge', () => {
  let sends = 0;
  const handler = createVisionSelectionHandler({
    cameraBridge: { send() { sends += 1; return true; } },
  });

  const result = invoke(handler, { side: 'middle', ordinal: 0 });

  assert.equal(sends, 0);
  assert.equal(result.code, 400);
  assert.equal(result.payload.accepted, false);
  assert.equal(result.payload.robot_control_enabled, false);
});
