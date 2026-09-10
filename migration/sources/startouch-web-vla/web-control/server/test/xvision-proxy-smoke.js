'use strict';

const assert = require('assert/strict');
const http = require('http');
const path = require('path');
const { spawn } = require('child_process');
const WebSocket = require('ws');
const { WebSocketServer } = WebSocket;

const HOST = '127.0.0.1';
const PROXY_PORT = Number(process.env.XVISION_PROXY_TEST_PORT || 3230);
const UPSTREAM_PORT = Number(process.env.XVISION_UPSTREAM_TEST_PORT || 3231);
const FRAME = Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\nXVISIO\r\n');

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({
        status: response.statusCode,
        headers: response.headers,
        body: Buffer.concat(chunks),
      }));
    });
    request.once('error', reject);
  });
}

async function waitForHttp(url) {
  let lastError = null;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await httpGet(url);
      if (response.status >= 200 && response.status < 300) return;
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }
  throw new Error(`proxy did not start: ${url}: ${lastError?.message || 'unknown error'}`);
}

async function waitFor(predicate, label) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const value = predicate();
    if (value) return value;
    await delay(50);
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill('SIGTERM');
  await Promise.race([new Promise(resolve => child.once('exit', resolve)), delay(1500)]);
  if (child.exitCode === null) child.kill('SIGKILL');
}

async function run() {
  const upstreamCommands = [];
  let upstreamSocket;
  const upstream = http.createServer((req, res) => {
    if (['/camera_lumos', '/camera_lumos_vision'].includes(req.url)) {
      res.writeHead(200, { 'Content-Type': 'multipart/x-mixed-replace; boundary=frame' });
      res.end(FRAME);
      return;
    }
    res.writeHead(404).end();
  });
  const upstreamWs = new WebSocketServer({ server: upstream, path: '/ws' });
  upstreamWs.on('connection', socket => {
    upstreamSocket = socket;
    socket.on('message', raw => upstreamCommands.push(JSON.parse(raw.toString())));
  });
  await new Promise((resolve, reject) => {
    upstream.once('error', reject);
    upstream.listen(UPSTREAM_PORT, HOST, resolve);
  });

  const output = [];
  const proxy = spawn(process.execPath, ['proxy.js'], {
    cwd: path.resolve(__dirname, '..'),
    env: {
      ...process.env,
      CAMERA_ENABLED: '0',
      XVISION_PROXY_ENABLED: '1',
      XVISION_SERVICE_URL: `http://${HOST}:${UPSTREAM_PORT}`,
      XVISION_WS_URL: `ws://${HOST}:${UPSTREAM_PORT}/ws`,
      STARTOUCH_SIMULATE: '1',
      STARTOUCH_PYTHON: 'python',
      WEB_HOST: HOST,
      WEB_PORT: String(PROXY_PORT),
      LUMOS_STREAM_URL: '',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  proxy.stdout.on('data', chunk => output.push(chunk.toString()));
  proxy.stderr.on('data', chunk => output.push(chunk.toString()));
  proxy.on('exit', (code, signal) => output.push(`[proxy exit] code=${code} signal=${signal}\n`));

  let browser;
  try {
    await waitForHttp(`http://${HOST}:${PROXY_PORT}/`);
    await waitFor(() => upstreamSocket, 'upstream websocket');

    for (const route of ['/camera/xvisio/vision', '/camera/xvisio/raw']) {
      const response = await httpGet(`http://${HOST}:${PROXY_PORT}${route}`);
      const body = response.body;
      assert.equal(response.status, 200);
      assert.equal(body.includes(Buffer.from('XVISIO')), true);
    }

    const browserMessages = [];
    browser = new WebSocket(`ws://${HOST}:${PROXY_PORT}/ws`);
    browser.on('message', raw => browserMessages.push(JSON.parse(raw.toString())));
    await new Promise((resolve, reject) => {
      browser.once('open', resolve);
      browser.once('error', reject);
    });
    browser.send(JSON.stringify({ cmd: 'select_vision_target', side: 'left', ordinal: 1 }));
    const selection = await waitFor(() => upstreamCommands[0], 'selection forwarding');
    assert.deepEqual(
      { cmd: selection.cmd, side: selection.side, ordinal: selection.ordinal },
      { cmd: 'select_bottle', side: 'left', ordinal: 1 }
    );
    assert.equal(typeof selection.request_id, 'string');

    upstreamSocket.send(JSON.stringify({
      type: 'detection_result',
      schema: 'thirdhand-va-detection-v2',
      ts: Date.now(),
      robot_control_enabled: false,
      hardware_validation: 'pending',
      status: 'locked',
      reasons: ['handeye_physical_validation_pending'],
      selection: { side: 'left', ordinal: 1 },
      targets: [{
        detection_id: 4,
        identity_id: 9,
        label: 'bottle',
        score: 0.91,
        selected: true,
        left_ordinal: 1,
        right_ordinal: 3,
        actionable: false,
        grasp_preview: { allowed: false, blockers: ['handeye_activation_locked'] },
      }],
    }));
    const detection = await waitFor(
      () => browserMessages.find(message => message.type === 'detection_result'),
      'normalized detection'
    );
    assert.equal(detection.objects[0].spatialLabel, 'L1/R3');
    assert.equal(detection.objects[0].actionable, false);
    assert.equal(detection.objects[0].blockers.includes('physical_grasp_execution_locked'), true);
    browser.send(JSON.stringify({
      cmd: 'start_vision_grasp',
      mode: 'auto',
      id: 4,
      position_m: [999, 999, 999],
    }));
    const rejection = await waitFor(
      () => browserMessages.find(message =>
        message.type === 'error' && /robot_execution_disabled/.test(message.msg || '')
      ),
      'locked grasp rejection'
    );
    assert.match(rejection.msg, /robot_execution_disabled/);
    console.log('PASS port 3000 proxies XVisio streams, events, and bounded selection commands');
  } catch (error) {
    console.error(output.join(''));
    throw error;
  } finally {
    if (browser) browser.terminate();
    await stopChild(proxy);
    upstreamWs.close();
    await new Promise(resolve => upstream.close(resolve));
  }
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
