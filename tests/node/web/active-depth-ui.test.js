'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.resolve(__dirname, '../../../apps/web/public/index.html'), 'utf8');
const source = fs.readFileSync(path.resolve(__dirname, '../../../apps/web/public/js/main.js'), 'utf8');

test('XVisio drawer has unique explicit active-depth controls and status fields', () => {
  for (const id of ['btn-active-depth-start', 'btn-active-depth-stop',
    'active-depth-phase', 'active-depth-target', 'active-depth-depth',
    'active-depth-pixel', 'active-depth-motion', 'active-depth-steps',
    'active-depth-reason']) {
    assert.equal((html.match(new RegExp(`id=["']${id}["']`, 'g')) || []).length, 1, id);
  }
  assert.match(html, /id="btn-active-depth-start"[^>]*disabled/);
  assert.match(html, /id="btn-active-depth-stop"[^>]*disabled/);
});

test('active depth starts only from button click and restores server-owned status', () => {
  assert.match(source, /btn-active-depth-start[\s\S]*addEventListener\('click'/);
  assert.match(source, /fetch\('\/api\/active-depth\/status'/);
  assert.match(source, /this\.ws\.on\('active_depth\.status'/);
  assert.doesNotMatch(source, /select_target[\s\S]{0,300}api\/active-depth\/start/);
});

test('browser active-depth block contains no direct robot execution or kinematics', () => {
  const start = source.indexOf('// === Active Depth Controls ===');
  const end = source.indexOf('// === End Active Depth Controls ===', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  assert.doesNotMatch(block, /move_joint|\/execution|TOKEN|forwardKinematics|joints_rad/);
  assert.match(source, /深度已连续有效/);
  assert.match(source, /操作员已停止/);
  assert.match(source, /状态不确定/);
});

test('vision target switching is correlated and reports acknowledgement', () => {
  assert.match(source, /pendingVisionSelection/);
  assert.match(source, /type: "select_target", stableId: obj\.stableId, requestId/);
  assert.match(source, /Math\.random\(\)\.toString\(16\)/);
  assert.match(source, /this\.visionWs\.on\("selection_result"/);
  assert.match(source, /视觉目标切换已发送/);
});
