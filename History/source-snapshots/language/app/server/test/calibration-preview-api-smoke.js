'use strict';

const assert = require('assert/strict');
const http = require('http');
const express = require('express');
const {
  CalibrationPreviewService,
  createCalibrationPreviewRouter,
} = require('../calibration-preview-api');

const JPEG = Buffer.from([0xff, 0xd8, 0x54, 0x48, 0x49, 0x52, 0x44, 0xff, 0xd9]);

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.listen(0, '127.0.0.1', resolve);
    server.once('error', reject);
  });
  return server.address().port;
}

async function close(server) {
  await new Promise(resolve => server.close(resolve));
}

async function run() {
  let upstreamClosed = 0;
  const upstream = http.createServer((_request, response) => {
    response.writeHead(200, {
      'content-type': 'multipart/x-mixed-replace; boundary=frame',
    });
    response.write(Buffer.concat([
      Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\n'),
      JPEG,
      Buffer.from('\r\n'),
    ]));
    response.once('close', () => { upstreamClosed += 1; });
  });
  const upstreamPort = await listen(upstream);
  const service = new CalibrationPreviewService({
    lumosUrl: `http://127.0.0.1:${upstreamPort}/lumos`,
    d435Url: `http://127.0.0.1:${upstreamPort}/d435`,
  });
  const app = express();
  app.use('/api/calibration-preview', createCalibrationPreviewRouter({
    service,
    isLoopback: () => true,
  }));
  const server = http.createServer(app);
  const port = await listen(server);
  try {
    for (const camera of ['lumos', 'd435']) {
      const response = await fetch(
        `http://127.0.0.1:${port}/api/calibration-preview/${camera}.jpg`
      );
      assert.equal(response.status, 200);
      assert.equal(response.headers.get('content-type'), 'image/jpeg');
      assert.equal(response.headers.get('cache-control'), 'no-store');
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), JPEG);
    }
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal(upstreamClosed, 2);

    const deniedApp = express();
    deniedApp.use('/api/calibration-preview', createCalibrationPreviewRouter({
      service,
      isLoopback: () => false,
    }));
    const deniedServer = http.createServer(deniedApp);
    const deniedPort = await listen(deniedServer);
    try {
      const denied = await fetch(
        `http://127.0.0.1:${deniedPort}/api/calibration-preview/lumos.jpg`
      );
      assert.equal(denied.status, 403);
    } finally {
      await close(deniedServer);
    }
  } finally {
    await close(server);
    await close(upstream);
  }
  console.log('PASS calibration preview converts endless MJPEG into bounded JPEG responses');
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
