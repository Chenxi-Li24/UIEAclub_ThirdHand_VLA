'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const ROOT = path.resolve(__dirname, '../../..');
const { runSimulation } = require('../../../tools/tcp_calibration/demo_simulated');

function digestProductionConfiguration() {
  const files = [
    'config', 'deployments',
  ].flatMap(directory => {
    const root = path.join(ROOT, directory);
    if (!fs.existsSync(root)) return [];
    return fs.readdirSync(root, { recursive: true, withFileTypes: true })
      .filter(entry => entry.isFile())
      .map(entry => path.join(entry.parentPath, entry.name))
      .filter(filename => !filename.includes(`${path.sep}artifacts${path.sep}`))
      .sort();
  });
  const hash = crypto.createHash('sha256');
  for (const filename of files) hash.update(filename).update(fs.readFileSync(filename));
  return hash.digest('hex');
}

test('simulated stages 0-6 restore after restart and never issue motion', async t => {
  const artifactRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-tcp-e2e-'));
  t.after(() => fs.rmSync(artifactRoot, { recursive: true, force: true }));
  const before = digestProductionConfiguration();

  const result = await runSimulation({ artifactRoot, quiet: true });

  assert.deepEqual(result.stages, [0, 1, 2, 3, 4, 5, 6]);
  assert.equal(result.fitSampleIds.length, 8);
  assert.equal(result.validationSampleIds.length, 3);
  assert.equal(new Set([...result.fitSampleIds, ...result.validationSampleIds]).size, 11);
  assert.equal(result.restored.stage, 'ready_to_finalize');
  assert.equal(result.restored.revision, 14);
  assert.ok(result.candidateId.startsWith('sha256:'));
  assert.ok(result.activeId.startsWith('sha256:'));
  assert.equal(result.rollbackActiveId, result.previousActiveId);
  assert.ok(result.outbound.every(message => message.cmd === 'software_stop'));
  assert.equal(result.motionCommandCount, 0);
  assert.equal(digestProductionConfiguration(), before);

  const active = JSON.parse(fs.readFileSync(path.join(artifactRoot, 'active-manifest.json'), 'utf8'));
  assert.equal(active.schema, 'thirdhand-gripper-tcp-active-v1');
  assert.equal(active.activeId, result.previousActiveId);
  assert.equal(fs.statSync(path.join(artifactRoot, 'active-manifest.json')).mode & 0o777, 0o600);
});
