'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');

const ROOT = path.resolve(__dirname, '../../..');
const MODULE = path.join(ROOT, 'apps/launcher/src/one-click.js');
const unix = { skip: process.platform === 'win32' };

function loadEnsure() {
  assert.ok(fs.existsSync(MODULE), 'one-click orchestration for 1034/1035 is missing');
  return require(MODULE).ensureOneClick;
}

async function fixture(t, { formalCode = 0, meituanCode = 0,
  payload = { serviceId: 'meituan-vision' }, httpCode = 200 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-one-click-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const formalRoot = path.join(dir, 'formal');
  const meituanRoot = path.join(dir, 'meituan');
  const calls = path.join(dir, 'calls');
  for (const [root, code] of [[formalRoot, formalCode], [meituanRoot, meituanCode]]) {
    fs.mkdirSync(root, { recursive: true });
    fs.writeFileSync(path.join(root, 'thirdhand'),
      '#!/usr/bin/env bash\nprintf "%s:%s\\n" "$PWD" "$*" >> "' + calls + '"\nexit ' + code + '\n');
  }
  const server = http.createServer((request, response) => {
    response.writeHead(request.url === '/health' ? httpCode : 404,
      { 'content-type': 'application/json' });
    response.end(typeof payload === 'string' ? payload : JSON.stringify(payload));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const port = server.address().port;
  const configDir = path.join(formalRoot, 'configs/runtime');
  fs.mkdirSync(configDir, { recursive: true });
  fs.writeFileSync(path.join(configDir, 'manual-control.json'), JSON.stringify({
    services: [{ id: 'vision', command: '${NODE}', args: [], port: 3100,
      env: { MEITUAN_VISION_HOST: '127.0.0.1', MEITUAN_VISION_PORT: String(port) } }]
  }));
  return { formalRoot, meituanRoot, calls, server, port };
}

test('one-click ensures formal and Meituan profiles in order, then validates shared vision', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t);
  const report = await ensure(f);
  assert.equal(report.overall, 'ready');
  assert.equal(report.services['meituan-web'].state, 'ready');
  assert.equal(report.services['meituan-vision'].state, 'ready');
  assert.equal(report.services['meituan-vision'].port, f.port);
  assert.deepEqual(fs.readFileSync(f.calls, 'utf8').trim().split('\n'), [
    f.formalRoot + ':ensure --profile manual-control',
    f.meituanRoot + ':ensure --profile meituan-web'
  ]);
});

test('formal startup failure cannot report all services ready', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t, { formalCode: 3 });
  const report = await ensure(f);
  assert.equal(report.overall, 'degraded');
  assert.equal(report.services['manual-control'].state, 'degraded');
  assert.equal(report.services['meituan-web'].state, 'ready');
});

test('1034 startup failure cannot report all services ready', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t, { meituanCode: 4 });
  const report = await ensure(f);
  assert.equal(report.overall, 'degraded');
  assert.equal(report.services['meituan-web'].reason, 'ensure_exit_4');
});

test('missing Meituan worktree is reported without running anything in its place', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t);
  const report = await ensure({ ...f, meituanRoot: path.join(f.meituanRoot, 'missing') });
  assert.equal(report.overall, 'degraded');
  assert.equal(report.services['meituan-web'].state, 'degraded');
  assert.equal(fs.readFileSync(f.calls, 'utf8').trim(), f.formalRoot + ':ensure --profile manual-control');
});

for (const [label, options, reason] of [
  ['wrong service', { payload: { serviceId: 'vision' } }, 'health_identity_mismatch:serviceId'],
  ['invalid JSON', { payload: 'not JSON' }, 'health_invalid_json'],
  ['HTTP failure', { httpCode: 503 }, 'health_http_503']
]) {
  test('1035 ' + label + ' fails readiness without starting a second vision owner', unix, async t => {
    const ensure = loadEnsure();
    const f = await fixture(t, options);
    const report = await ensure(f);
    assert.equal(report.overall, 'degraded');
    assert.equal(report.services['meituan-vision'].reason, reason);
    assert.equal(fs.readFileSync(f.calls, 'utf8').trim().split('\n').length, 2);
  });
}

test('closed 1035 port is reported as degraded without restarting shared vision', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t);
  await new Promise(resolve => f.server.close(resolve));
  const report = await ensure(f);
  assert.equal(report.overall, 'degraded');
  assert.match(report.services['meituan-vision'].reason, /ECONNREFUSED/);
  assert.equal(fs.readFileSync(f.calls, 'utf8').trim().split('\n').length, 2);
});

test('ensure-all CLI returns success for all-ready and failure for partial readiness', unix, async t => {
  loadEnsure();
  const f = await fixture(t);
  const run = () => promisify(execFile)(process.execPath,
    [path.join(ROOT, 'apps/launcher/src/cli.js'), 'ensure-all', '--json'], {
      env: { ...process.env, THIRDHAND_FORMAL_ROOT: f.formalRoot, THIRDHAND_MEITUAN_ROOT: f.meituanRoot }
    });
  const result = await run();
  assert.equal(JSON.parse(result.stdout).overall, 'ready');
  await new Promise(resolve => f.server.close(resolve));
  await assert.rejects(run(), error =>
    error.code === 1 && JSON.parse(error.stdout).overall === 'degraded');
});

test('one-click restores a missing listener on the same trusted vision entry and preserves calibration', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t);
  await new Promise(resolve => f.server.close(resolve));
  const entry = path.join(f.formalRoot, 'services/vision/src/server.js');
  fs.mkdirSync(path.dirname(entry), { recursive: true });
  fs.writeFileSync(entry, `
    const http = require('node:http');
    const sockets = [];
    const body = { serviceId: 'vision', pid: process.pid, sharedOwnerPid: process.pid, camera: { status: 'ready' },
      calibration: process.env.TEST_CALIBRATION, bridge: process.env.VISION_BRIDGE_SCRIPT,
      runtime: Object.fromEntries(['VISION_BRIDGE_SCRIPT', 'VISION_PYTHON', 'VISION_CONFIG',
        'THIRDHAND_VA_HANDEYE', 'THIRDHAND_ROBOT_URDF', 'MEITUAN_BATTERY_MODULE']
        .map(key => [key, process.env[key]])) };
    const listen = (port, serviceId) => {
      const server = http.createServer((req, res) => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(JSON.stringify({ ...body, serviceId }));
      });
      server.listen(port, '127.0.0.1');
      sockets.push(server);
    };
    listen(Number(process.env.VISION_PORT), 'vision');
    if (process.env.MEITUAN_VISION_PORT) listen(Number(process.env.MEITUAN_VISION_PORT), 'meituan-vision');
    process.on('SIGTERM', () => {
      for (const server of sockets) server.close();
      setTimeout(() => process.exit(0), 20);
    });
  `);
  const mainPortProbe = http.createServer();
  await new Promise(resolve => mainPortProbe.listen(0, '127.0.0.1', resolve));
  const mainPort = mainPortProbe.address().port;
  await new Promise(resolve => mainPortProbe.close(resolve));
  const cfgFile = path.join(f.formalRoot, 'configs/runtime/manual-control.json');
  const cfg = JSON.parse(fs.readFileSync(cfgFile));
  cfg.services[0].port = mainPort;
  cfg.services[0].bind = '127.0.0.1';
  cfg.services[0].args = [entry];
  const preserved = {
    VISION_BRIDGE_SCRIPT: 'custom-camera-bridge.py', VISION_PYTHON: 'original-python',
    VISION_CONFIG: 'original-vision.yaml', THIRDHAND_VA_HANDEYE: 'original-handeye.json',
    THIRDHAND_ROBOT_URDF: 'original-robot.urdf', MEITUAN_BATTERY_MODULE: 'original-battery.py',
  };
  Object.assign(cfg.services[0].env, Object.fromEntries(
    Object.keys(preserved).map(key => [key, 'replacement-' + key]),
  ));
  fs.writeFileSync(cfgFile, JSON.stringify(cfg));
  const { spawn } = require('node:child_process');
  const child = spawn(process.execPath, [entry], {
    cwd: f.formalRoot,
    env: { ...process.env, VISION_PORT: String(mainPort), MEITUAN_VISION_PORT: '',
      TEST_CALIBRATION: 'preserve-me', ...preserved },
    stdio: 'ignore'
  });
  const pids = new Set([child.pid]);
  t.after(() => {
    for (const pid of pids) {
      try {
        const args = fs.readFileSync('/proc/' + pid + '/cmdline', 'utf8').split('\0');
        if (args[1] === entry) process.kill(pid, 'SIGTERM');
      } catch (error) { if (!['ENOENT', 'ESRCH'].includes(error.code)) throw error; }
    }
  });
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch('http://127.0.0.1:' + mainPort + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const report = await ensure(f);
  assert.equal(report.overall, 'ready', JSON.stringify(report.services));
  assert.equal(report.services['meituan-vision'].action, 'shared-owner-restarted');
  const after = await fetch('http://127.0.0.1:' + f.port + '/health').then(r => r.json());
  pids.add(after.pid);
  assert.notEqual(after.pid, child.pid);
  assert.equal(after.calibration, 'preserve-me');
  assert.equal(after.bridge, 'custom-camera-bridge.py');
  assert.deepEqual(after.runtime, preserved);
  const reused = await ensure(f);
  assert.equal(reused.overall, 'ready');
  assert.equal(reused.services['meituan-vision'].action, 'shared-owner-probe');
  assert.equal((await fetch('http://127.0.0.1:' + mainPort + '/health').then(r => r.json())).pid, after.pid);
});

test('repair refuses a lookalike entry outside the deployments directory without signaling it', unix, async t => {
  const ensure = loadEnsure();
  const f = await fixture(t);
  await new Promise(resolve => f.server.close(resolve));
  const entry = path.join(path.dirname(f.formalRoot), 'tools/vision/vision_server_with_state.js');
  fs.mkdirSync(path.dirname(entry), { recursive: true });
  fs.writeFileSync(entry, `
    const http = require('node:http');
    const serve = (port, serviceId) => http.createServer((req, res) => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ serviceId, pid: process.pid, sharedOwnerPid: process.pid }));
    }).listen(Number(port), '127.0.0.1');
    serve(process.env.VISION_PORT, 'vision');
    if (process.env.MEITUAN_VISION_PORT) serve(process.env.MEITUAN_VISION_PORT, 'meituan-vision');
  `);
  const probe = http.createServer();
  await new Promise(resolve => probe.listen(0, '127.0.0.1', resolve));
  const mainPort = probe.address().port;
  await new Promise(resolve => probe.close(resolve));
  const configPath = path.join(f.formalRoot, 'configs/runtime/manual-control.json');
  const config = JSON.parse(fs.readFileSync(configPath));
  config.services[0].port = mainPort;
  config.services[0].bind = '127.0.0.1';
  fs.writeFileSync(configPath, JSON.stringify(config));
  const child = require('node:child_process').spawn(process.execPath, [entry], {
    cwd: f.formalRoot, env: { ...process.env, VISION_PORT: String(mainPort), MEITUAN_VISION_PORT: '' },
    stdio: 'ignore'
  });
  t.after(async () => {
    const ids = [child.pid];
    try { ids.push((await fetch('http://127.0.0.1:' + f.port + '/health').then(r => r.json())).pid); } catch {}
    for (const pid of ids) {
      try {
        if (fs.readFileSync('/proc/' + pid + '/cmdline', 'utf8').split('\0')[1] === entry) process.kill(pid, 'SIGTERM');
      } catch (error) { if (!['ENOENT', 'ESRCH'].includes(error.code)) throw error; }
    }
  });
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch('http://127.0.0.1:' + mainPort + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  const report = await ensure(f);
  assert.equal(report.overall, 'degraded');
  assert.equal(report.services['meituan-vision'].repairReason, 'vision_entry_unrecognized');
  assert.equal((await fetch('http://127.0.0.1:' + mainPort + '/health').then(r => r.json())).pid, child.pid);
});
