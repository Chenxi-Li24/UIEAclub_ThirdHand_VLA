'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const { loadConfig } = require('../../../apps/meituan/src/config');

function fakeProxy() {
  class Socket extends EventEmitter {
    static OPEN = 1;
    static CONNECTING = 0;
    static CLOSING = 2;
    constructor() { super(); this.readyState = 1; this.sent = []; }
    send(data) { this.sent.push(JSON.parse(data)); }
    close() { this.readyState = 3; }
    terminate() { this.close(); }
  }
  class Bridge extends EventEmitter {
    start() {}
    shutdown() {}
    publicStatus() { return {}; }
    getRobotState() { return { connected: false }; }
  }
  const file = path.resolve(__dirname, '../../../apps/meituan/src/robot-proxy.js');
  const realRequire = createRequire(file);
  const module = { exports: {} };
  const sandbox = { module, console, require: name => {
    if (name === 'ws') return { WebSocket: Socket };
    if (name === './language/language-upstream-bridge') return { LanguageUpstreamBridge: Bridge };
    return realRequire(name);
  } };
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), sandbox, { filename: file });
  const config = loadConfig({ WEB_PORT: '1034', LANGUAGE_REAL_CONTROL: '1',
    DIRECTIONAL_CONTROL_ENABLED: '1', DIRECTIONAL_REAL_CONTROL: '1',
    CAMERA_X_PROBE_ENABLED: '1', CAMERA_X_REAL_CONTROL: '1' });
  const proxy = new module.exports.RobotProxy('ws://127.0.0.1:9/ws', config.language);
  const browser = new Socket();
  proxy.attach(browser);
  return { proxy, browser, upstream: [...proxy.sessions][0].upstream };
}

test('Meituan keeps real-control flags off even with old enabling environment', () => {
  const config = loadConfig({ WEB_PORT: '1034', LANGUAGE_REAL_CONTROL: '1',
    DIRECTIONAL_REAL_CONTROL: '1', CAMERA_X_PROBE_ENABLED: '1', CAMERA_X_REAL_CONTROL: '1' });
  assert.equal(config.language.realControlEnabled, false);
  assert.equal(config.language.directionalRealControlEnabled, false);
  assert.equal(config.language.cameraProbeEnabled, false);
  assert.equal(config.language.cameraRealControlEnabled, false);
});

test('Meituan rejects raw robot mutations but keeps status, IK preview and stop available', () => {
  const { proxy, browser, upstream } = fakeProxy();
  for (const cmd of ['connect', 'disconnect', 'servo', 'move_l', 'preset', 'gripper']) {
    browser.emit('message', Buffer.from(JSON.stringify({ cmd, request_id: cmd })));
    assert.equal(upstream.sent.length, 0, cmd + ' must not reach 3000');
    assert.equal(browser.sent.at(-1).code, 'meituan_motion_not_enabled');
    assert.equal(browser.sent.at(-1).request_id, cmd);
  }
  for (const cmd of ['status', 'ping', 'preview_ik', 'software_stop', 'estop']) {
    browser.emit('message', Buffer.from(JSON.stringify({ cmd })));
    assert.equal(upstream.sent.at(-1).cmd, cmd);
  }
  proxy.close();
});

test('Meituan confirmation cannot dispatch an external motion Skill', () => {
  const { proxy, browser, upstream } = fakeProxy();
  let dispatched = false;
  proxy.languageController.decide = () => { dispatched = true; };
  browser.emit('message', Buffer.from(JSON.stringify({ type: 'confirmation.decision',
    decision: 'approve', candidateId: 'read-only-candidate', traceId: 'read-only-trace' })));
  assert.equal(dispatched, false);
  assert.equal(upstream.sent.length, 0);
  assert.equal(browser.sent.at(-1).status, 'blocked');
  assert.equal(browser.sent.at(-1).code, 'meituan_motion_not_enabled');
  proxy.close();
});

test('Meituan cannot start active-depth motion through HTTP', async t => {
  const { createWebGateway } = require('../../../apps/meituan/src/server');
  let started = false;
  const coordinator = Object.assign(new EventEmitter(), {
    start: async () => { started = true; return {}; }, status: () => ({}), close() {},
  });
  const proxy = { broadcast() {}, close() {}, getRobotState: () => ({}) };
  const temporary = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'meituan-read-only-'));
  const gateway = createWebGateway({ env: { WEB_PORT: '1034' }, coordinator,
    host: '127.0.0.1', port: 0, readyFile: path.join(temporary, 'web.ready'),
    robotProxy: proxy, visionProxy: proxy, voiceProxy: proxy });
  t.after(async () => { await gateway.close(); fs.rmdirSync(temporary); });
  const address = await gateway.start();
  try {
    const response = await fetch('http://127.0.0.1:' + address.port
      + '/api/active-depth/start', { method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ stableId: 1 }) });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, 'meituan_motion_not_enabled');
    assert.equal(started, false);
  } finally { await gateway.close(); }
});
