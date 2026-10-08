'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { createWebServer } = require('../../../apps/bottle_pick/web_server');

test('supervised HTTP preview is read-only and blocked start never sends motion', async t => {
  const calls = [];
  const supervisedSession = {
    preview(targetId) { calls.push(['preview', targetId]); return {
      previewId: 'preview-1', targetId, executable: false,
      blockers: ['calibration_not_approved'], plan: null,
    }; },
    snapshot() { return { phase: 'idle' }; },
    start(request) { calls.push(['start', request]); return {
      accepted: false, reason: 'preview_not_executable',
    }; },
    next(request) { calls.push(['next', request]); return { accepted: false }; },
    stop(request) { calls.push(['stop', request]); return { accepted: true }; },
  };
  const server = createWebServer({
    cameraBridge: { subscribeMjpeg() {}, getInfo() { return { ready: true }; } },
    operatorController: { start() {}, stop() {}, snapshot() { return { active: false }; } },
    supervisedSession, robotControlEnabled: true, robotReady: () => true,
    port: 0,
  });
  const address = await server.start();
  t.after(() => server.stop());
  const base = `http://127.0.0.1:${address.port}`;
  const preview = await fetch(`${base}/api/va/test/preview?target_id=1`);
  assert.equal(preview.status, 200);
  assert.equal((await preview.json()).executable, false);
  const start = await fetch(`${base}/api/va/test/start`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ requestId: 'req-1', previewId: 'preview-1' }),
  });
  assert.equal(start.status, 423);
  assert.deepEqual(calls.map(call => call[0]), ['preview', 'start']);
  const invalidNext = await fetch(`${base}/api/va/test/next`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ requestId: 'req-1', expectedPhase: 'open' }),
  });
  assert.equal(invalidNext.status, 400);
  assert.equal(calls.length, 2);
});
