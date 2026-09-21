'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { spawnSync } = require('node:child_process');
const { buildActiveDepthPreview } = require('../../../apps/web/src/active-depth/preview');

const matrix_4x4 = [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
const mount = { matrix_4x4, camera_mount_id: 'camera-a', registration_id: 'registration-a',
  physical_validation: { status: 'pending' } };
const observation = { frameId: 42, observedAtMs: 1000, selectedStableId: 2,
  camera_mount_id: 'camera-a', registration_id: 'registration-a',
  targets: [{ stable_id: 2, centroid_xy: [562,327] }] };
const robotSnapshot = { jointsDeg: [0,0,0,0,0,0], observedAtMs: 1000, stateName: 'IDLE',
  jointLimitsDeg: [[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]] };

function preview(changes = {}) {
  return buildActiveDepthPreview({ observation, robotSnapshot, mount, nowMs: 1100, ...changes });
}

test('pending mount always keeps offline preview non-executable', () => {
  const result = preview();
  assert.equal(result.mode, 'offline');
  assert.equal(result.executable, false);
  assert.equal(result.targetId, 2);
  assert.deepEqual(result.targetPixel, [562,327]);
  assert.ok(result.blockers.includes('mount_unverified'));
});

test('stale or switched target and missing joint evidence block proposal', () => {
  assert.equal(preview({ observation: { ...observation, selectedStableId: 3 } }).proposal, null);
  assert.equal(preview({ observation: { ...observation, observedAtMs: 700 } }).proposal, null);
  assert.equal(preview({ robotSnapshot: { ...robotSnapshot, jointsDeg: null } }).proposal, null);
  assert.equal(preview({ observation: { ...observation, registration_id: 'other' } }).proposal, null);
  const lost = preview({ observation: { ...observation,
    targets: [{ stable_id: 2, centroid_xy: [562,327], track_state: 'lost' }] } });
  assert.equal(lost.proposal, null);
  assert.ok(lost.blockers.includes('target_not_confirmed'));
});

test('inconsistent post-step RGB movement stops correction', () => {
  const result = preview({ observation: { ...observation,
    targets: [{ stable_id: 2, centroid_xy: [570,327] }] },
  previousStep: { targetId: 2, beforePixel: [562,327],
    predictedPixel: [550,327], completedAtMs: 900 } });
  assert.equal(result.executable, false);
  assert.ok(result.blockers.includes('response_inconsistent'));
  assert.equal(result.proposal, null);
});

test('small signed movement cannot hide a larger sideways regression', () => {
  const result = preview({ observation: { ...observation,
    targets: [{ stable_id: 2, centroid_xy: [560,390] }] },
  robotSnapshot: { ...robotSnapshot, startJointsDeg: [0,0,0,0,0,0] },
  previousStep: { targetId: 2, beforePixel: [562,327],
    predictedPixel: [550,327], completedAtMs: 900 } });
  assert.equal(result.proposal, null);
  assert.ok(result.blockers.includes('response_inconsistent'));
});

test('reflected camera mount is invalid even if rows are orthogonal', () => {
  const reflection = [[-1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
  const result = preview({ mount: { ...mount, matrix_4x4: reflection } });
  assert.equal(result.proposal, null);
  assert.ok(result.blockers.includes('mount_invalid'));
});

test('fixture CLI rejects execute flag before touching robot adapters', () => {
  const cli = path.resolve(__dirname, '../../../tools/active-depth/preview.js');
  const run = spawnSync(process.execPath, [cli, '--execute'], { encoding: 'utf8' });
  assert.equal(run.status, 2);
  assert.match(run.stderr, /unsupported.*execute/i);
});

test('fixture CLI prints a read-only proposal and its blockers', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'active-depth-'));
  try {
    const fixturePath = path.join(directory, 'fixture.json');
    fs.writeFileSync(fixturePath, JSON.stringify({ observation, robotSnapshot, mount, nowMs: 1100 }));
    const cli = path.resolve(__dirname, '../../../tools/active-depth/preview.js');
    const run = spawnSync(process.execPath,
      [cli, '--fixture', fixturePath, '--target-id', '2'], { encoding: 'utf8' });
    assert.equal(run.status, 2);
    const result = JSON.parse(run.stdout);
    assert.equal(result.executable, false);
    assert.ok(result.blockers.includes('mount_unverified'));
    assert.equal(result.proposal.pixelEstimateKind, 'rotation_only_bearing');
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});
