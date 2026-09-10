'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

for (const name of ['VLA_PROVIDER', 'VLA_MODEL', 'VLA_TIMEOUT_MS', 'VLA_AUDIT_LOG']) {
  delete process.env[name];
}
delete require.cache[require.resolve('../config')];

const config = require('../config');
const {
  createGroundingBrowserHandler,
  createGroundingProvider,
} = require('../vla/browser-handler');
const { createBrowserCommandRouter } = require('../vla/command-router');

assert.deepEqual(config.vla, {
  provider: 'disabled',
  model: 'gpt-5.6-terra',
  timeoutMs: 8000,
  auditLog: path.resolve(__dirname, '../../../artifacts/vision/vla-grounding/events.jsonl'),
});

const calls = { submit: [], cancel: [] };
const sent = [];
const grounding = {
  submit(values) {
    calls.submit.push({ operator: values.operator, query: values.query });
    values.send({ type: 'grounding_state', status: 'analyzing' });
    return Promise.resolve();
  },
  cancel(operator, reason) {
    calls.cancel.push({ operator, reason });
    return true;
  },
};
const ws = Object.freeze({ id: 'operator-1' });
const handler = createGroundingBrowserHandler({
  grounding,
  send: (operator, event) => sent.push({ operator, event }),
});

(async () => {
  assert.deepEqual(
    await handler({ cmd: 'ground_language_target', query: '夹取可乐' }, ws),
    { handled: true, accepted: true }
  );
  assert.deepEqual(calls.submit, [{ operator: ws, query: '夹取可乐' }]);
  assert.deepEqual(sent, [{ operator: ws, event: { type: 'grounding_state', status: 'analyzing' } }]);

  const rejected = await handler(
    { cmd: 'ground_language_target', query: '可乐', identityId: 12 },
    ws
  );
  assert.deepEqual(rejected, {
    handled: true, accepted: false, reason: 'browser_command_keys_invalid',
  });
  assert.equal(sent.at(-1).operator, ws);
  assert.deepEqual(sent.at(-1).event, {
    type: 'grounding_state',
    status: 'rejected',
    requestId: null,
    identityId: null,
    explanation: null,
    reason: 'browser_command_keys_invalid',
    provider: null,
    modelId: null,
    latencyMs: null,
  });
  assert.equal(calls.submit.length, 1);

  assert.equal(handler.cancel(ws, 'browser_disconnected'), true);
  assert.deepEqual(calls.cancel, [{ operator: ws, reason: 'browser_disconnected' }]);

  const disabled = createGroundingProvider({ provider: 'disabled', model: 'gpt-5.6-terra' });
  await assert.rejects(
    disabled.select({}),
    error => error && error.code === 'provider_unavailable'
  );
  assert.equal(disabled.providerName, 'disabled');
  assert.throws(
    () => createGroundingProvider({ provider: 'surprise', model: 'gpt-5.6-terra' }),
    /vla_provider_invalid/
  );
  const openai = createGroundingProvider(
    { provider: 'openai', model: 'gpt-5.6-terra', timeoutMs: 8000 },
    { OPENAI_API_KEY: 'server-test-secret' }
  );
  assert.equal(openai.providerName, 'openai');
  assert.equal(JSON.stringify(openai).includes('server-test-secret'), false);

  const legacyCalls = [];
  const router = createBrowserCommandRouter({
    handleGrounding: handler,
    handleLegacy: (message, operator) => legacyCalls.push({ message, operator }),
  });
  await router({ cmd: 'ground_language_target', query: '夹取可乐' }, ws);
  assert.deepEqual(legacyCalls, []);
  router({ cmd: 'servo', joints: [] }, ws);
  assert.deepEqual(legacyCalls, [{ message: { cmd: 'servo', joints: [] }, operator: ws }]);

  const source = fs.readFileSync(path.resolve(__dirname, '../proxy.js'), 'utf8');
  for (const required of [
    'createBrowserCommandRouter({',
    'handleGrounding: handleGroundingBrowserCommand',
    'handleLegacy: handleLegacyBrowserCommand',
    "grounding.cancel(ws, 'browser_disconnected')",
    "cancelGroundingForAll('software_stop')",
    "cancelGroundingForAll('camera_stopped')",
    "cancelGroundingForAll('camera_error')",
    "cancelGroundingForAll('vision_error')",
    'cameraBridge.getLatestVisionSnapshot()',
    'visionStatus.groundingSnapshot(Date.now())',
  ]) {
    assert.equal(source.includes(required), true, `proxy wiring missing: ${required}`);
  }
  console.log('PASS VLA proxy wiring is requester-only, fail-closed, and actuator-free');
})().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
