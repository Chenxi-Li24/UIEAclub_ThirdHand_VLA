'use strict';

const assert = require('assert/strict');
const http = require('http');
const { spawn } = require('child_process');
const path = require('path');

const HOST = '127.0.0.1';
const PROXY_PORT = Number(process.env.LUMOS_PROXY_TEST_PORT || 3220);
const UPSTREAM_PORT = Number(process.env.LUMOS_UPSTREAM_TEST_PORT || 3221);
const FRAME = Buffer.from(
  '--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nTEST\r\n'
);

delete process.env.LUMOS_SNAPSHOT_URL;
delete require.cache[require.resolve('../config')];
assert.equal(
  require('../config').camera.lumosSnapshotUrl,
  'http://127.0.0.1:3001/frame_raw.jpg',
  'online perception must default to native calibrated Lumos pixels'
);

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitForHttp(url) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await delay(100);
  }
  throw new Error(`proxy did not start: ${url}`);
}

function stopChild(child) {
  if (!child || child.exitCode !== null) return Promise.resolve();
  child.kill('SIGTERM');
  return Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    delay(2000).then(() => child.kill('SIGKILL')),
  ]);
}

async function run() {
  const upstream = http.createServer((_req, res) => {
    res.writeHead(200, {
      'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
      'Content-Length': String(FRAME.length),
    });
    res.end(FRAME);
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
      STARTOUCH_SIMULATE: '1',
      STARTOUCH_PYTHON: 'python',
      WEB_HOST: HOST,
      WEB_PORT: String(PROXY_PORT),
      LUMOS_STREAM_URL: `http://${HOST}:${UPSTREAM_PORT}/camera_lumos`,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  proxy.stdout.on('data', chunk => output.push(chunk.toString()));
  proxy.stderr.on('data', chunk => output.push(chunk.toString()));

  try {
    await waitForHttp(`http://${HOST}:${PROXY_PORT}/diag`);
    const response = await fetch(`http://${HOST}:${PROXY_PORT}/camera_lumos`);
    const body = Buffer.from(await response.arrayBuffer());
    assert.equal(response.status, 200);
    assert.match(response.headers.get('content-type') || '', /boundary=frame/);
    assert.equal(body.includes(Buffer.from('TEST')), true);

    const page = await fetch(`http://${HOST}:${PROXY_PORT}/camera-test.html`).then(
      value => value.text()
    );
    assert.match(page, /data-stream="\/camera_lumos"/);
    assert.match(page, /data-overlay-stream="\/camera_lumos_vision"/);
    assert.match(page, /data-stream="\/camera"/);
    assert.doesNotMatch(page, /src="\/(?:camera_lumos_vision|camera)"/);
    console.log('PASS same-origin Lumos proxy and dual-camera page are live');
  } catch (error) {
    console.error(output.join(''));
    throw error;
  } finally {
    await stopChild(proxy);
    await new Promise(resolve => upstream.close(resolve));
  }
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
