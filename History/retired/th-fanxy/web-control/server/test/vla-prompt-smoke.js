'use strict';

const assert = require('assert/strict');
const { buildOpenAIRequest, PROMPT_VERSION } = require('../vla/prompt');

const evidence = {
  frameId: 1842,
  frameMonotonicNs: 987654321,
  observedAtMs: 1000,
  imageSha256: `sha256:${'a'.repeat(64)}`,
  jpeg: Buffer.from([0xff, 0xd8, 0x43, 0x4f, 0x4b, 0x45, 0xff, 0xd9]),
  candidates: [
    { identityId: 12, detectionId: 3, label: 'bottle', identityStatus: 'confirmed', detectionScore: 0.94 },
    { identityId: 15, detectionId: 4, label: 'can', identityStatus: 'confirmed', detectionScore: 0.91 },
  ],
  allowedIdentityIds: [12, 15],
};

const request = buildOpenAIRequest({ query: '夹取可乐', evidence, model: 'gpt-5.6-terra' });
assert.equal(PROMPT_VERSION, 'thirdhand-grounding-v1');
assert.equal(request.model, 'gpt-5.6-terra');
assert.deepEqual(request.reasoning, { effort: 'low' });
assert.equal(request.store, false);
assert.equal(request.max_output_tokens, 300);
assert.equal(request.input[0].role, 'system');
assert.equal(request.input[1].role, 'user');
const userContent = request.input[1].content;
assert.equal(userContent[0].type, 'input_text');
assert.match(userContent[0].text, /夹取可乐/);
assert.match(userContent[0].text, /"identity_id":12/);
assert.match(userContent[0].text, /"identity_id":15/);
assert.equal(userContent[1].type, 'input_image');
assert.match(userContent[1].image_url, /^data:image\/jpeg;base64,/);
assert.equal(userContent[1].detail, 'low');
const format = request.text.format;
assert.equal(format.type, 'json_schema');
assert.equal(format.name, 'thirdhand_target_selection');
assert.equal(format.strict, true);
assert.equal(format.schema.additionalProperties, false);
assert.deepEqual(format.schema.required.sort(), [
  'ambiguous', 'decision', 'explanation', 'identity_id', 'semantic_score',
].sort());
assert.deepEqual(format.schema.properties.decision.enum, ['select', 'clarify', 'none']);
assert.deepEqual(format.schema.properties.identity_id.anyOf[0].enum, [12, 15]);
assert.equal(JSON.stringify(request).includes('OPENAI_API_KEY'), false);

assert.throws(
  () => buildOpenAIRequest({ query: '夹取可乐', evidence, model: '' }),
  /model/
);

console.log('PASS GPT request uses fixed prompt, strict schema, and server-owned model');
