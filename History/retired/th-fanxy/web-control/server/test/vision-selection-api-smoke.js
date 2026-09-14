'use strict';

const assert = require('assert');
const { createVisionSelectionHandler } = require('../vision-selection-api');

function invoke(body) {
  const sent = [];
  const response = {
    statusCode: null,
    body: null,
    status(code) { this.statusCode = code; return this; },
    json(value) { this.body = value; return this; },
  };
  const handler = createVisionSelectionHandler({
    cameraBridge: { send(message) { sent.push(message); return true; } },
    makeRequestId: () => 'generated-id',
  });
  handler({ body }, response);
  return { sent, response };
}

{
  const { sent, response } = invoke({ index: 2, request_id: 'voice-2' });
  assert.strictEqual(response.statusCode, 202);
  assert.deepStrictEqual(response.body.selection, { index: 2 });
  assert.deepStrictEqual(sent, [{
    type: 'select_bottle', side: 'left', ordinal: 2, request_id: 'voice-2',
  }]);
}

{
  const { sent, response } = invoke({ side: 'right', ordinal: 1 });
  assert.strictEqual(response.statusCode, 202);
  assert.deepStrictEqual(response.body.selection, { side: 'right', ordinal: 1 });
  assert.strictEqual(sent[0].side, 'right');
}

{
  const { sent, response } = invoke({ index: 0 });
  assert.strictEqual(response.statusCode, 400);
  assert.strictEqual(response.body.reason, 'selection_requires_positive_index');
  assert.deepStrictEqual(sent, []);
}

console.log('PASS numeric bottle selection API and legacy compatibility');
