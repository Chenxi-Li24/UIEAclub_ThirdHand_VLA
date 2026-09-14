const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { discoverSkills } = require('../../../platform/skill_registry/src/registry');

test('discovers manifests without loading worker code', async () => {
  const skills = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  assert.ok(skills.some(skill => skill.id === 'vision.describe-scene'));
  assert.ok(skills.some(skill => skill.id === 'manipulation.pick-and-place'));
});

test('ACT remains unavailable without checkpoint and services', async () => {
  const skills = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  const act = skills.find(skill => skill.id === 'policy.act');
  assert.equal(act.status, 'unavailable');
  assert.ok(act.unavailableReasons.includes('model:policy.act'));
  assert.ok(act.unavailableReasons.includes('implementation_not_migrated'));
});

test('discovery order is deterministic', async () => {
  const skills = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  assert.deepEqual(skills.map(skill => skill.id), [...skills.map(skill => skill.id)].sort());
});

test('gripper control requires Robot and Startouch but no vision or model', async () => {
  const unavailable = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: {}, devices: {}, models: {} },
  });
  const missing = unavailable.find(skill => skill.id === 'manipulation.gripper-control');
  assert.ok(missing);
  assert.deepEqual(missing.unavailableReasons, ['device:startouch', 'service:robot']);

  const available = await discoverSkills({
    skillsRoot: path.resolve('skills'),
    resources: { services: { robot: 'ready' }, devices: { startouch: 'ready' }, models: {} },
  });
  assert.equal(available.find(skill => skill.id === 'manipulation.gripper-control').status, 'ready');
});
