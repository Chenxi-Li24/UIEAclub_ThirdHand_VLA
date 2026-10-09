'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const entry = path.resolve(__dirname, '../../../services/vision/src/server.js');

for (const enabled of [false, true]) {
  test('shared vision works without local battery modules, external listener ' + enabled, () => {
    const result = spawnSync(process.execPath, ['-e', String.raw`
      const assert = require('node:assert/strict');
      const fs = require('node:fs');
      const os = require('node:os');
      const path = require('node:path');
      const { EventEmitter } = require('node:events');
      const Module = require('node:module');
      const load = Module._load;
      Module._load = function(request, parent, ...rest) {
        if (parent?.filename === process.env.TEST_VISION_ENTRY && request === './meituan-raw-view') {
          throw new Error('local battery migration copy is unavailable');
        }
        return load.call(this, request, parent, ...rest);
      };
      const runtime = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-external-'));
      const externalRoot = path.join(runtime, 'external');
      const adapter = path.join(externalRoot, 'services/vision/src/meituan-raw-view.js');
      fs.mkdirSync(path.dirname(adapter), { recursive: true });
      fs.writeFileSync(adapter, '(' + function () {
        const http = require('node:http');
        module.exports.createMeituanRawView = ({ camera, host, port }) => {
          const server = http.createServer((_req, res) => {
            res.setHeader('content-type', 'application/json');
            res.end(JSON.stringify({ origin: 'external', camera: camera.status().camera }));
          });
          return {
            address: () => server.address(),
            start: () => new Promise(resolve => server.listen(port, host, resolve)),
            close: () => new Promise(resolve => server.close(resolve))
          };
        };
      }.toString() + ')();');
      process.env.MEITUAN_WORKTREE = externalRoot;
      const camera = new EventEmitter();
      Object.assign(camera, {
        meituanReady: true,
        start() {}, close() {}, send() { return true; },
        status() { return { camera: { status: 'ready' }, inference: { status: 'ready' } }; },
        subscribe() { return true; }, unsubscribe() {}
      });
      let service;
      (async () => {
        try {
          const { createVisionService } = require(process.env.TEST_VISION_ENTRY);
          service = createVisionService({ camera, readyFile: path.join(runtime, 'ready') });
          const address = await service.start();
          const health = await fetch('http://127.0.0.1:' + address.port + '/health').then(r => r.json());
          assert.equal(health.serviceId, 'vision');
          const battery = service.meituanAddress();
          if (process.env.TEST_LISTENER === '1') {
            assert.ok(battery);
            const result = await fetch('http://127.0.0.1:' + battery.port + '/health').then(r => r.json());
            assert.equal(result.origin, 'external');
            assert.equal(result.camera.status, 'ready');
          } else assert.equal(battery, null);
        } finally {
          await service?.close();
          fs.rmSync(runtime, { recursive: true, force: true });
        }
      })().catch(error => { console.error(error); process.exitCode = 1; });
    `], { encoding: 'utf8', timeout: 10000, env: {
      ...process.env, TEST_VISION_ENTRY: entry, TEST_LISTENER: enabled ? '1' : '0',
      VISION_HOST: '127.0.0.1', VISION_PORT: '0',
      MEITUAN_VISION_HOST: '127.0.0.1', MEITUAN_VISION_PORT: enabled ? '0' : '',
      MEITUAN_WORKTREE: '', MEITUAN_BATTERY_ENABLE: '1'
    }});
    assert.equal(result.status, 0, result.stderr || result.error?.message);
  });
}
