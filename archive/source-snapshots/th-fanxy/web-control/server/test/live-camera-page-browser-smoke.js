'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const express = require('express');
const { spawn } = require('child_process');
const WebSocket = require('ws');

const EDGE_CANDIDATES = [
  process.env.EDGE_PATH,
  '/usr/bin/microsoft-edge',
  '/usr/bin/microsoft-edge-stable',
  '/usr/bin/google-chrome',
].filter(Boolean);
const EDGE_PATH = EDGE_CANDIDATES.find(candidate => fs.existsSync(candidate));
const WEB_ROOT = path.resolve(__dirname, '..', '..', 'web');
const WEB_PORT = Number(process.env.LIVE_CAMERA_TEST_PORT || 43510);
const DEBUG_PORT = Number(process.env.LIVE_CAMERA_DEBUG_PORT || 49510);
const PAGE_URL = `http://127.0.0.1:${WEB_PORT}/camera-test.html`;
const SCREENSHOT_PATH = path.join(os.tmpdir(), 'thirdhand-live-camera-controlled.png');
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-live-camera-edge-'));

if (!EDGE_PATH) throw new Error('Microsoft Edge or Google Chrome was not found');

let server;
let websocketServer;
let edge;
let cdp;
let commandId = 0;
let overlayReady = false;
const pending = new Map();
const requests = [];
const exceptions = [];

function imageSvg(title, color) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540">
    <rect width="960" height="540" fill="${color}"/>
    <text x="480" y="270" text-anchor="middle" fill="white" font-size="52"
      font-family="sans-serif">${title}</text>
  </svg>`;
}

function statusSnapshot() {
  return {
    online: false,
    modelReady: false,
    d435Ready: true,
    lumosReady: true,
    roles: {
      canonicalRgb: 'lumos_rgb',
      metricDepth: 'd435_depth',
      debugRgb: 'd435_rgb',
    },
    sequences: { lumos: 10, d435: 20 },
    metrics: { latencyMs: null, latencyP95Ms: null, gpuMemoryReservedGib: null },
    targets: [],
    blockers: ['vision_unavailable'],
    sourceAgeMs: 0,
    stale: false,
    taskCheckpointValidated: false,
    robotExecutionEnabled: false,
    activeViewExecutionEnabled: false,
    activeView: {
      executionEnabled: false,
      reports: [],
      control: {
        phase: 'idle', sessionId: null, identityId: null, proposalId: null,
        reasons: [], evidenceIdsShort: [], moveReady: false,
        requiresConfirmation: true,
      },
    },
    error: null,
  };
}

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
  throw new Error('live-camera DevTools target did not become ready');
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
      || 'live-camera evaluation failed'
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
  app.get('/api/vision/status', (_request, response) => response.json(statusSnapshot()));
  app.get('/camera_lumos', (_request, response) => {
    response.type('image/svg+xml').send(imageSvg('REAL LUMOS RAW', '#174f78'));
  });
  app.get('/camera', (_request, response) => {
    response.type('image/svg+xml').send(imageSvg('REAL D435', '#28633d'));
  });
  app.get('/camera_lumos_vision', (_request, response) => {
    if (!overlayReady) {
      response.status(503).send('overlay not ready');
      return;
    }
    response.type('image/svg+xml').send(imageSvg('LUMOS OVERLAY', '#6c3d87'));
  });
  app.use(express.static(WEB_ROOT));
  server = await new Promise((resolve, reject) => {
    const listener = app.listen(WEB_PORT, '127.0.0.1', () => resolve(listener));
    listener.once('error', reject);
  });
  websocketServer = new WebSocket.Server({ server, path: '/ws' });

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
  await command('Page.navigate', { url: PAGE_URL });
  await waitFor(`document.readyState === 'complete' && document.body.dataset.mode === 'live'`);
  await waitFor(`['lumos', 'd435'].every(id => {
    const image = document.getElementById(id); return image.complete && image.naturalWidth > 0;
  })`);

  const initial = await evaluate(`(() => {
    const visible = id => {
      const rect = document.getElementById(id).getBoundingClientRect();
      return rect.top >= 0 && rect.bottom <= window.innerHeight && rect.width > 0 && rect.height > 0;
    };
    return {
      lumosSource: document.getElementById('lumos').src,
      d435Source: document.getElementById('d435').src,
      lumosVisibleInViewport: visible('lumos'),
      d435VisibleInViewport: visible('d435'),
      overlayButton: document.getElementById('lumos-overlay-toggle')?.textContent ?? '',
      safety: document.getElementById('safety-lock').textContent,
    };
  })()`);

  await evaluate(`document.getElementById('lumos-overlay-toggle').click()`);
  await waitFor(`document.getElementById('lumos-stream-status').textContent ===
    '算法叠加不可用，继续显示原始画面'`);
  const afterFailedOverlay = await evaluate(`({
    source: document.getElementById('lumos').src,
    status: document.getElementById('lumos-stream-status').textContent,
  })`);

  overlayReady = true;
  await evaluate(`document.getElementById('lumos-overlay-toggle').click()`);
  await waitFor(`document.getElementById('lumos').src.includes('/camera_lumos_vision')`);
  const overlaySource = await evaluate(`document.getElementById('lumos').src`);

  await evaluate(`document.getElementById('lumos-overlay-toggle').click()`);
  await waitFor(`document.getElementById('lumos').src.endsWith('/camera_lumos')`);
  const returnedRawSource = await evaluate(`document.getElementById('lumos').src`);

  const screenshot = await command('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
  });
  fs.writeFileSync(SCREENSHOT_PATH, Buffer.from(screenshot.result.data, 'base64'));

  assert.match(initial.lumosSource, /\/camera_lumos$/);
  assert.match(initial.d435Source, /\/camera$/);
  assert.equal(initial.lumosVisibleInViewport, true);
  assert.equal(initial.d435VisibleInViewport, true);
  assert.match(initial.overlayButton, /算法叠加/);
  assert.match(initial.safety, /robotExecutionEnabled = false/);
  assert.match(afterFailedOverlay.source, /\/camera_lumos$/);
  assert.equal(afterFailedOverlay.status, '算法叠加不可用，继续显示原始画面');
  assert.match(overlaySource, /\/camera_lumos_vision/);
  assert.match(returnedRawSource, /\/camera_lumos$/);
  assert.equal(requests.some(url => url.endsWith('/camera_lumos')), true);
  assert.equal(requests.some(url => url.endsWith('/camera')), true);
  assert.deepEqual(exceptions, []);

  console.log('PASS live camera page shows raw streams and bounds overlay fallback');
  console.log(`LIVE_CAMERA_SCREENSHOT ${SCREENSHOT_PATH}`);
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
    if (websocketServer) websocketServer.close();
    if (server) await new Promise(resolve => server.close(resolve));
    try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
  });
