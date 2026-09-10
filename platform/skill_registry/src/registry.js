const fs = require('node:fs');
const path = require('node:path');
const YAML = require('yaml');
const { createContractValidator } = require('../../contracts/src/validator');
const { evaluateRequirements } = require('./resource-status');

function manifestPaths(skillsRoot) {
  const paths = [];
  if (!fs.existsSync(skillsRoot)) return paths;
  for (const group of fs.readdirSync(skillsRoot, { withFileTypes: true }).filter(item => item.isDirectory())) {
    const groupPath = path.join(skillsRoot, group.name);
    for (const skill of fs.readdirSync(groupPath, { withFileTypes: true }).filter(item => item.isDirectory())) {
      const candidate = path.join(groupPath, skill.name, 'manifest.yaml');
      if (fs.existsSync(candidate)) paths.push(candidate);
    }
  }
  return paths.sort();
}

async function discoverSkills({ skillsRoot, resources }) {
  const contracts = createContractValidator();
  const ids = new Set();
  const descriptors = [];
  for (const manifestPath of manifestPaths(path.resolve(skillsRoot))) {
    const manifest = YAML.parse(fs.readFileSync(manifestPath, 'utf8'));
    const validation = contracts.validate('thirdhand.skill-manifest.v1', manifest);
    if (!validation.ok) {
      throw new Error(`invalid Skill manifest ${manifestPath}: ${JSON.stringify(validation.errors)}`);
    }
    if (ids.has(manifest.id)) throw new Error(`duplicate Skill id: ${manifest.id}`);
    ids.add(manifest.id);
    const reasons = evaluateRequirements(manifest, resources, path.dirname(manifestPath));
    descriptors.push({
      id: manifest.id,
      version: manifest.version,
      summary: manifest.summary,
      risk: manifest.risk,
      operations: [...manifest.operations],
      status: reasons.length === 0 ? 'ready' : 'unavailable',
      unavailableReasons: reasons,
      manifestPath,
    });
  }
  return descriptors.sort((left, right) => left.id.localeCompare(right.id));
}

module.exports = { discoverSkills, manifestPaths };
