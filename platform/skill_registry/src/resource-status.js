const fs = require('node:fs');
const path = require('node:path');

function isReady(value) {
  return value === true || value === 'ready' || value?.status === 'ready';
}

function evaluateRequirements(manifest, resources, manifestDir) {
  const reasons = [];
  const groups = [
    ['service', 'services'],
    ['device', 'devices'],
    ['model', 'models'],
  ];
  for (const [singular, plural] of groups) {
    for (const id of manifest.requires[plural]) {
      if (!isReady(resources[plural]?.[id])) reasons.push(`${singular}:${id}`);
    }
  }
  if (!fs.existsSync(path.resolve(manifestDir, manifest.entrypoint))) {
    reasons.push('implementation_not_migrated');
  }
  return [...new Set(reasons)].sort();
}

module.exports = { evaluateRequirements, isReady };
