'use strict';

const http = require('node:http');

function json(response, status, payload) {
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store'
  });
  response.end(JSON.stringify(payload));
}

// A second HTTP listener for the existing CameraProcess, never a camera/model owner.
function createMeituanRawView({ camera, host = '127.0.0.1', port = 1035,
  recognitionEnabled = process.env.MEITUAN_BATTERY_ENABLE === '1' }) {
  if (!camera || typeof camera.subscribe !== 'function') {
    throw new TypeError('Meituan raw view requires the existing camera owner');
  }
  const clients = new Set();
  let recognition = null;
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    if (request.method !== 'GET') {
      response.setHeader('allow', 'GET');
      json(response, 405, { code: 'read_only' });
      return;
    }
    if (recognition?.handleHttp(request, response, pathname)) return;
    if (pathname === '/health' || pathname === '/api/meituan/vision/status') {
      const status = camera.status();
      json(response, 200, {
        serviceId: 'meituan-vision',
        mode: recognition ? 'battery' : 'raw-only',
        sharedOwnerPid: process.pid,
        camera: status.camera,
        batteryDetection: recognition ? recognition.status() : { status: 'not_implemented' },
        robotControlEnabled: false
      });
      return;
    }
    if (pathname === '/') {
      response.writeHead(200, {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store'
      });
      response.end('<!doctype html><html lang="zh-CN"><meta charset="UTF-8">' +
        '<meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>美团视觉 · 原始画面</title>' +
        '<style>body{margin:0;padding:24px;background:#0b101c;color:#e5edf5;font:16px sans-serif}' +
        'main{max-width:1100px;margin:auto}h1{font-size:20px;color:#00c9e6}' +
        'img{display:block;width:100%;background:#050910;border-radius:8px}p{color:#a6b2c1}</style>' +
        '<main><h1>美团视觉 · 原始画面</h1><img src="/camera/xvisio/raw" alt="相机原始画面">' +
        '<p>电池框选和颜色识别尚未接入。</p></main></html>');
      return;
    }
    if (pathname === '/camera/xvisio/vision') {
      json(response, 501, {
        code: 'battery_detection_not_implemented',
        message: '电池识别尚未接入',
        detections: []
      });
      return;
    }
    if (pathname !== '/camera/xvisio/raw') {
      json(response, 404, { code: 'not_found' });
      return;
    }
    const status = camera.status();
    if (status.camera.status !== 'ready') {
      json(response, 503, {
        code: 'camera_unavailable',
        message: status.camera.error || 'Camera is not ready'
      });
      return;
    }
    response.writeHead(200, {
      'content-type': 'multipart/x-mixed-replace; boundary=frame',
      'cache-control': 'no-store, no-cache, must-revalidate',
      connection: 'close'
    });
    clients.add(response);
    response.once('close', () => {
      clients.delete(response);
      camera.unsubscribe('raw', response);
    });
    if (!camera.subscribe('raw', response)) response.end();
  });

  if (recognitionEnabled) {
    const { attachRecognition } = require('./meituan-recognition');
    recognition = attachRecognition({ server, camera, host });
  }

  return {
    address() { return server.address(); },
    async start() {
      await new Promise((resolve, reject) => {
        const onError = error => reject(error);
        server.once('error', onError);
        server.listen(port, host, () => {
          server.removeListener('error', onError);
          resolve();
        });
      });
      return server.address();
    },
    async close() {
      await recognition?.close();
      for (const response of clients) {
        camera.unsubscribe('raw', response);
        response.end();
      }
      clients.clear();
      if (!server.listening) return;
      await new Promise(resolve => {
        server.close(resolve);
        server.closeAllConnections();
      });
    }
  };
}

module.exports = { createMeituanRawView };
