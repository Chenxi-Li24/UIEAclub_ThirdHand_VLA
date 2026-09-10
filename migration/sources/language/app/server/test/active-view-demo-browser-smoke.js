'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const express = require('express');
const WebSocket = require('ws');

const EDGE_CANDIDATES = [
  process.env.EDGE_PATH,
  '/usr/bin/microsoft-edge',
  '/usr/bin/microsoft-edge-stable',
  '/usr/bin/google-chrome',
].filter(Boolean);
const EDGE_PATH = EDGE_CANDIDATES.find(candidate => fs.existsSync(candidate));
const WEB_ROOT = path.resolve(__dirname, '..', '..', 'web');
const WEB_PORT = Number(process.env.ACTIVE_VIEW_DEMO_TEST_PORT || 43130);
const DEBUG_PORT = Number(process.env.ACTIVE_VIEW_DEMO_DEBUG_PORT || 49238);
const PAGE_URL = `http://127.0.0.1:${WEB_PORT}/camera-test.html?demo=1`;
const SCREENSHOT_PATH = path.join(os.tmpdir(), 'thirdhand-active-view-demo.png');
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-active-view-demo-edge-'));

if (!EDGE_PATH) throw new Error('Microsoft Edge or Google Chrome was not found');

let server;
let edge;
let cdp;
let commandId = 0;
const pending = new Map();
const requests = [];
const exceptions = [];

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function waitForDebugTarget() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`);
      const targets = await response.json();
      const target = targets.find(item => item.type === 'page');
      if (target?.webSocketDebuggerUrl) return target;
    } catch {}
    await delay(100);
  }
  throw new Error('demo browser DevTools target did not become ready');
}

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++commandId;
    pending.set(id, { resolve, reject });
    cdp.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await command('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.result?.exceptionDetails) {
    throw new Error(
      response.result.exceptionDetails.exception?.description
      || response.result.exceptionDetails.text
      || 'demo browser evaluation failed'
    );
  }
  return response.result?.result?.value;
}

async function waitFor(expression, timeoutMs = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(expression)) return;
    await delay(100);
  }
  throw new Error(`condition timed out: ${expression}`);
}

async function run() {
  const app = express();
  app.use(express.static(WEB_ROOT));
  server = await new Promise((resolve, reject) => {
    const listener = app.listen(WEB_PORT, '127.0.0.1', () => resolve(listener));
    listener.once('error', reject);
  });

  edge = spawn(EDGE_PATH, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${profileDir}`,
    '--window-size=1440,1000',
    'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });

  const target = await waitForDebugTarget();
  cdp = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    cdp.once('open', resolve);
    cdp.once('error', reject);
  });
  cdp.on('message', raw => {
    const message = JSON.parse(raw.toString());
    if (message.id && pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
      else request.resolve(message);
      return;
    }
    if (message.method === 'Network.requestWillBeSent') {
      requests.push(message.params.request.url);
    }
    if (message.method === 'Runtime.exceptionThrown') {
      exceptions.push(
        message.params.exceptionDetails.exception?.description
        || message.params.exceptionDetails.text
      );
    }
  });

  await command('Runtime.enable');
  await command('Page.enable');
  await command('Network.enable');
  await command('Page.addScriptToEvaluateOnNewDocument', {
    source: `
      window.__demoNetworkCounts = { fetch: 0, webSocket: 0 };
      const originalFetch = window.fetch.bind(window);
      window.fetch = (...args) => {
        window.__demoNetworkCounts.fetch += 1;
        return originalFetch(...args);
      };
      const OriginalWebSocket = window.WebSocket;
      window.WebSocket = class CountedWebSocket extends OriginalWebSocket {
        constructor(...args) {
          window.__demoNetworkCounts.webSocket += 1;
          super(...args);
        }
      };
    `,
  });
  await command('Page.navigate', { url: PAGE_URL });
  await waitFor(`document.readyState === 'complete' && document.body.dataset.mode === 'demo'`);
  await waitFor(`document.querySelector('#active-targets button') !== null`);

  await evaluate(`document.querySelector('#active-targets button').click()`);
  await waitFor(`document.getElementById('active-phase').textContent === 'waiting_operator_confirmation'`);
  await waitFor(`document.getElementById('confirm-step').disabled === false`);

  await evaluate(`document.getElementById('confirm-step').click()`);
  await waitFor(`document.getElementById('active-stable').textContent === '2 / 5'`);
  await waitFor(`document.getElementById('confirm-step').disabled === false`);

  await evaluate(`document.getElementById('confirm-step').click()`);
  await waitFor(`document.getElementById('active-phase').textContent === 'grasp_preview'`);

  const result = await evaluate(`(() => ({
    fetchCount: window.__demoNetworkCounts.fetch,
    webSocketCount: window.__demoNetworkCounts.webSocket,
    phase: document.getElementById('active-phase').textContent,
    preview: document.getElementById('grasp-preview').textContent,
    stable: document.getElementById('active-stable').textContent,
    depth: document.getElementById('active-depth').textContent,
    banner: document.getElementById('demo-banner')?.textContent ?? '',
    safety: document.getElementById('safety-lock').textContent,
    hasGraspExecutionButton: [...document.querySelectorAll('button')]
      .some(button => button.textContent.includes('执行抓取')),
    startDisabled: document.querySelector('#active-targets button')?.disabled,
    lumosPanel: document.getElementById('lumos').src,
    d435Panel: document.getElementById('d435').src,
  }))()`);
  const screenshot = await command('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  fs.writeFileSync(SCREENSHOT_PATH, Buffer.from(screenshot.result.data, 'base64'));

  assert.equal(result.fetchCount, 0);
  assert.equal(result.webSocketCount, 0);
  assert.equal(result.phase, 'grasp_preview');
  assert.match(result.preview, /仅预览，不能执行抓取/);
  assert.equal(result.stable, '5 / 5');
  assert.match(result.depth, /中央比例 0\.92/);
  assert.match(result.banner, /纯浏览器模拟/);
  assert.match(result.safety, /robotExecutionEnabled = false/);
  assert.match(result.safety, /activeViewExecutionEnabled = false/);
  assert.equal(result.hasGraspExecutionButton, false);
  assert.equal(result.startDisabled, true);
  assert.match(result.lumosPanel, /^data:image\/svg\+xml/);
  assert.match(result.d435Panel, /^data:image\/svg\+xml/);
  assert.equal(
    requests.some(url => /\/(camera|camera_lumos_vision)(?:\?|$)/.test(url)),
    false
  );
  assert.deepEqual(exceptions, []);

  console.log('PASS active-view demo completes in-browser without network or actuator transport');
  console.log(`DEMO_SCREENSHOT ${SCREENSHOT_PATH}`);
}

run()
  .catch(error => {
    console.error(`FAIL ${error.stack || error.message}`);
    process.exitCode = 1;
  })
  .finally(async () => {
    try { await command('Browser.close'); } catch {}
    try { cdp?.close(); } catch {}
    if (edge && edge.exitCode === null) edge.kill();
    if (server) await new Promise(resolve => server.close(resolve));
    try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
  });
