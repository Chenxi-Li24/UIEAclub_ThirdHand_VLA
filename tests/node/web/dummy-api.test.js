'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createWebGateway } = require('../../../apps/web/src/server');

test('Dummy API is explicit, same-origin, strictly bounded and closes only its manager', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dummy-api-'));
  const calls = [];
  const proxy = { close() {}, attach() {}, broadcast() {}, getRobotState() { return null; } };
  const dummyController = {
    async status() { return { phase: 'stopped' }; },
    async frame() { return { state: { frame_id: 1 }, jpeg_base64: null }; },
    async start(body) { calls.push(body); if (!body.authorized) throw Object.assign(new Error(), { code: 'dummy_authorization_required' }); return { phase: 'starting' }; },
    stop() { calls.push('stop'); return { phase: 'stopping' }; },
    async close() { calls.push('close'); },
  };
  const gateway = createWebGateway({ host: '127.0.0.1', port: 0, readyFile: path.join(root, 'ready'),
    dummyController, robotProxy: proxy, visionProxy: proxy, voiceProxy: proxy });
  const { port } = await gateway.start();
  t.after(async () => { await gateway.close(); fs.rmSync(root, { recursive: true, force: true }); });
  const base = `http://127.0.0.1:${port}`;
  assert.equal((await fetch(`${base}/api/dummy/status`).then(r => r.json())).phase, 'stopped');
  assert.equal(calls.length, 0);
  const post = (route, body, headers = {}) => fetch(`${base}/api/dummy/${route}`, {
    method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify(body) });
  assert.equal((await post('start', { authorized: true, keywords: false }, { origin: 'https://evil.invalid' })).status, 403);
  assert.equal((await post('start', { authorized: true, keywords: false }, { 'sec-fetch-site': 'cross-site' })).status, 403);
  assert.equal((await post('start', { authorized: true, keywords: false, command: 'anything' })).status, 400);
  assert.equal((await post('stop', { pid: 1234 })).status, 400);
  assert.equal((await post('start', { padding: 'a'.repeat(17000) })).status, 413);
  assert.equal(calls.length, 0);
  assert.equal((await post('start', { authorized: false, keywords: true })).status, 403);
  assert.equal((await post('start', { authorized: true, keywords: false }, { origin: base })).status, 202);
  assert.deepEqual(calls[1], { authorized: true, keywords: false });
  assert.equal((await post('stop', {})).status, 202);
  assert.equal(calls[2], 'stop');
});
