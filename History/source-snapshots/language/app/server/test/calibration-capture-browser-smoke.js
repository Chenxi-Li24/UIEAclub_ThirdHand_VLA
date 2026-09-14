'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const express = require('express');
const { spawn } = require('child_process');
const WebSocket = require('ws');

const BROWSER = [
  process.env.EDGE_PATH,
  '/usr/bin/microsoft-edge',
  '/usr/bin/microsoft-edge-stable',
  '/usr/bin/google-chrome',
].filter(Boolean).find(candidate => fs.existsSync(candidate));
const WEB_ROOT = path.resolve(__dirname, '..', '..', 'web');
const WEB_PORT = Number(process.env.CALIBRATION_BROWSER_TEST_PORT || 43530);
const DEBUG_PORT = Number(process.env.CALIBRATION_BROWSER_DEBUG_PORT || 49530);
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-calibration-edge-'));
const SCREENSHOT = path.join(os.tmpdir(), 'thirdhand-calibration-capture.png');

if (!BROWSER) throw new Error('Microsoft Edge or Google Chrome was not found');

function imageSvg(title, color, width, height) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
    <rect width="100%" height="100%" fill="${color}"/>
    <text x="50%" y="50%" text-anchor="middle" fill="white" font-size="52"
      font-family="sans-serif">${title}</text>
  </svg>`;
}

function report() {
  return {
    schema_version: 1,
    ok: true,
    action: 'status',
    phase: 'fit_collect',
    progress: { current: 2, required: 12, purpose: 'fit' },
    sample: {
      id: 'fit-02',
      purpose: 'fit',
      common_points: 52,
      d435_reprojection_rmse_px: 0.38,
      lumos_reprojection_median_px: null,
      lumos_reprojection_p95_px: 118.7,
      capture_skew_ms: 7.2,
      passes_pixel_gate: true,
    },
    fit_metrics: null,
    relative_extrinsic_validated: false,
    remaining_blockers: [
      'relative_extrinsic_refit_missing',
      'handeye_validation_missing',
      'table_validation_missing',
    ],
    safety: { motion_or_robot_access: false, executable: false },
  };
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function waitForTarget() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try {
      const targets = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`).then(value => value.json());
      const target = targets.find(item => item.type === 'page');
      if (target?.webSocketDebuggerUrl) return target;
    } catch {}
    await delay(100);
  }
  throw new Error('browser debug target did not become ready');
}

async function run() {
  const app = express();
  let postCount = 0;
  const requests = [];
  app.use((request, _response, next) => {
    requests.push(request.path);
    next();
  });
  app.get('/api/calibration-preview/lumos.jpg', (_request, response) => {
    response.type('image/svg+xml').send(imageSvg('LUMOS LIVE', '#146078', 800, 800));
  });
  app.get('/api/calibration-preview/d435.jpg', (_request, response) => {
    response.type('image/svg+xml').send(imageSvg('D435 LIVE', '#276947', 800, 600));
  });
  app.get('/api/calibration/status', (_request, response) => response.json(report()));
  app.post('/api/calibration/capture-fit', (_request, response) => {
    postCount += 1;
    response.status(422).json({
      schema_version: 1,
      ok: false,
      error: { code: 'pose_not_distinct', message: 'safe public message' },
    });
  });
  app.use(express.static(WEB_ROOT));
  const server = await new Promise((resolve, reject) => {
    const listener = app.listen(WEB_PORT, '127.0.0.1', () => resolve(listener));
    listener.once('error', reject);
  });
  const browser = spawn(BROWSER, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--window-size=1500,1000',
    'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });
  let cdp;
  let commandId = 0;
  const pending = new Map();
  const exceptions = [];

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
      throw new Error(response.result.exceptionDetails.exception?.description || 'evaluation failed');
    }
    return response.result?.result?.value;
  }

  async function waitFor(expression) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (await evaluate(expression)) return;
      await delay(100);
    }
    throw new Error(`condition timed out: ${expression}`);
  }

  try {
    const target = await waitForTarget();
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
      } else if (message.method === 'Runtime.exceptionThrown') {
        exceptions.push(message.params.exceptionDetails.text);
      }
    });
    await command('Runtime.enable');
    await command('Page.enable');
    await command('Page.navigate', {
      url: `http://127.0.0.1:${WEB_PORT}/calibration-capture.html`,
    });
    await waitFor(`document.readyState === 'complete'`);
    await waitFor(`document.getElementById('progress-text').textContent === '2 / 12'`);
    await waitFor(`['calibration-lumos', 'calibration-d435'].every(id => {
      const image = document.getElementById(id);
      return image.complete && image.naturalWidth > 0;
    })`);

    const initial = await evaluate(`(() => ({
      progressClasses: [...document.querySelectorAll('#progress-grid span')]
        .map(node => node.className),
      lumosVisible: document.getElementById('calibration-lumos').getBoundingClientRect().width > 0,
      d435Visible: document.getElementById('calibration-d435').getBoundingClientRect().width > 0,
      safety: document.querySelector('.safety-banner').textContent,
      phase: document.getElementById('phase-label').textContent,
      action: document.getElementById('capture-button').textContent,
      buttons: document.querySelectorAll('button').length,
    }))()`);
    assert.deepEqual(initial.progressClasses.slice(0, 3), ['done', 'done', 'pending']);
    assert.equal(initial.lumosVisible, true);
    assert.equal(initial.d435Visible, true);
    assert.match(initial.safety, /不移动机械臂或夹爪/);
    assert.match(initial.phase, /采集拟合姿态/);
    assert.equal(initial.action, '采集拟合姿态');
    assert.equal(initial.buttons, 1);
    assert.equal(requests.includes('/api/calibration-preview/lumos.jpg'), true);
    assert.equal(requests.includes('/api/calibration-preview/d435.jpg'), true);
    assert.equal(requests.includes('/camera_lumos'), false);
    assert.equal(requests.includes('/camera_d435_raw'), false);

    await evaluate(`document.getElementById('capture-button').click()`);
    await waitFor(`document.getElementById('capture-result').textContent.includes('15 mm')`);
    assert.equal(postCount, 1);
    assert.deepEqual(exceptions, []);

    const screenshot = await command('Page.captureScreenshot', {
      format: 'png',
      captureBeyondViewport: false,
    });
    fs.writeFileSync(SCREENSHOT, Buffer.from(screenshot.result.data, 'base64'));
    console.log('PASS calibration capture page shows both cameras and actionable progress');
    console.log(`CALIBRATION_CAPTURE_SCREENSHOT ${SCREENSHOT}`);
  } finally {
    try { await command('Browser.close'); } catch {}
    try { cdp?.close(); } catch {}
    if (browser.exitCode === null) browser.kill();
    await new Promise(resolve => server.close(resolve));
    try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  }
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
