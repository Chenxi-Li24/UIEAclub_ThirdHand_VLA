'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

function loadConfig(enabled, realControlEnabled) {
  if (enabled === undefined) delete process.env.DIRECTIONAL_CONTROL_ENABLED;
  else process.env.DIRECTIONAL_CONTROL_ENABLED = enabled;
  if (realControlEnabled === undefined) delete process.env.DIRECTIONAL_REAL_CONTROL;
  else process.env.DIRECTIONAL_REAL_CONTROL = realControlEnabled;
  delete require.cache[require.resolve('../config')];
  return require('../config');
}

let config = loadConfig(undefined, undefined);
assert.equal(config.language.directionalEnabled, false);
assert.equal(config.language.directionalRealControlEnabled, false);

config = loadConfig('1', '1');
assert.equal(config.language.directionalEnabled, true);
assert.equal(config.language.directionalRealControlEnabled, true);

const source = fs.readFileSync(path.resolve(__dirname, '../proxy.js'), 'utf8');
for (const required of [
  'new DirectionalJointOrchestrator({',
  'enabled: config.language.directionalEnabled',
  'realControlEnabled: config.language.directionalRealControlEnabled',
  "candidate.skill === DIRECTIONAL_SKILL",
  'directionalOrchestrator.register(ws, candidate)',
  'directionalOrchestrator.decide(ws, message)',
  'directionalOrchestrator.handleBridgeEvent(message)',
  'directionalOrchestrator.disconnect(ws)',
  'directional: directionalOrchestrator.runtimeConfig()',
]) {
  assert.equal(source.includes(required), true, `proxy directional wiring missing: ${required}`);
}

console.log('PASS directional proxy wiring is isolated and defaults to preview-only');
