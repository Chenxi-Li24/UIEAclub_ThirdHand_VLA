const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { ServiceSupervisor } = require('../../../apps/launcher/src/service-supervisor');
const { processStartMarker } = require('../../../apps/launcher/src/service-supervisor');
const { readState, writeStateAtomic } = require('../../../apps/launcher/src/state-store');

async function reservePort() {
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  const port = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  return port;
}

test('starts once and stops in descending shutdown order', async (t) => {
  const events = [];
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-launcher-'));
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [
      {
        id: 'robot',
        command: process.execPath,
        args: [path.resolve('tools/fixtures/fake_service.js')],
        shutdownOrder: 100,
        enabled: true,
      },
      {
        id: 'vision',
        command: process.execPath,
        args: [path.resolve('tools/fixtures/fake_service.js')],
        shutdownOrder: 50,
        enabled: true,
      },
    ],
    onEvent: event => events.push(event),
  });
  t.after(async () => {
    await supervisor.stopAll();
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });

  await supervisor.startAll();
  const firstPids = (await supervisor.status()).map(item => item.pid);
  await supervisor.startAll();
  const secondPids = (await supervisor.status()).map(item => item.pid);

  assert.deepEqual(secondPids, firstPids);
  assert.deepEqual((await supervisor.status()).map(item => item.state), ['ready', 'ready']);
  await supervisor.stopAll();
  assert.deepEqual(
    events.filter(event => event.type === 'stopped').map(event => event.serviceId),
    ['robot', 'vision'],
  );
});

test('readiness timeout terminates the child it started', async () => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-timeout-'));
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    startTimeoutMs: 75,
    stopTimeoutMs: 500,
    services: [{
      id: 'never-ready',
      command: process.execPath,
      args: ['-e', 'setInterval(() => {}, 60000)'],
      shutdownOrder: 1,
      enabled: true,
    }],
  });

  await assert.rejects(supervisor.startAll(), /readiness timeout/);
  const child = supervisor.children.get('never-ready');
  await new Promise(resolve => setTimeout(resolve, 100));

  assert.equal(processStartMarker(child.pid), null);
  fs.rmSync(runtimeDir, { recursive: true, force: true });
});

test('identity mismatch is persisted as not_owned without signaling the PID', async () => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-not-owned-'));
  const statePath = path.join(runtimeDir, 'run', 'state.json');
  const service = {
    id: 'foreign',
    command: process.execPath,
    args: [path.resolve('tools/fixtures/fake_service.js')],
    shutdownOrder: 1,
    enabled: true,
  };
  writeStateAtomic(statePath, {
    schemaVersion: 1,
    authorizationState: 'active',
    services: [{
      id: 'foreign',
      pid: process.pid,
      processStartMarker: processStartMarker(process.pid),
      commandHash: 'wrong-command-hash',
      status: 'ready',
    }],
  });
  const supervisor = new ServiceSupervisor({ runtimeDir, services: [service] });

  await supervisor.stopAll();

  const state = readState(statePath);
  assert.equal(state.authorizationState, 'revoked');
  assert.equal(state.services[0].status, 'not_owned');
  fs.rmSync(runtimeDir, { recursive: true, force: true });
});

test('external listening port blocks every spawn during preflight', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-external-'));
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  t.after(async () => {
    await new Promise(resolve => listener.close(resolve));
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [
      {
        id: 'blocked',
        command: process.execPath,
        args: [path.resolve('tools/fixtures/fake_service.js')],
        bind: '127.0.0.1',
        port: listener.address().port,
        shutdownOrder: 2,
        enabled: true,
      },
      {
        id: 'later',
        command: process.execPath,
        args: [path.resolve('tools/fixtures/fake_service.js')],
        shutdownOrder: 1,
        enabled: true,
      },
    ],
  });

  await assert.rejects(
    supervisor.startAll(),
    error => error.code === 'external_service_ownership'
      && error.services[0].id === 'blocked'
      && error.services[0].reason === 'external_port_in_use',
  );
  assert.equal(supervisor.children.size, 0);
  const blocked = (await supervisor.status()).find(item => item.id === 'blocked');
  assert.equal(blocked.state, 'not_owned');
  assert.equal(blocked.reason, 'external_port_in_use');
  assert.equal(blocked.port, listener.address().port);
});

test('matching launcher identity owns an occupied service port', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-owned-'));
  const statePath = path.join(runtimeDir, 'run', 'state.json');
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  const service = {
    id: 'owned',
    command: process.execPath,
    args: ['-e', 'setInterval(() => {}, 60000)'],
    bind: '127.0.0.1',
    port: listener.address().port,
    shutdownOrder: 1,
    enabled: true,
  };
  writeStateAtomic(statePath, {
    schemaVersion: 1,
    authorizationState: 'revoked',
    services: [{
      id: service.id,
      pid: process.pid,
      processStartMarker: processStartMarker(process.pid),
      commandHash: require('../../../apps/launcher/src/service-supervisor').commandHash(service),
      status: 'ready',
    }],
  });
  const supervisor = new ServiceSupervisor({ runtimeDir, services: [service] });
  t.after(async () => {
    await new Promise(resolve => listener.close(resolve));
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });

  const preflight = await supervisor.preflight();
  assert.deepEqual(preflight, {
    ok: true,
    services: [{
      id: 'owned',
      state: 'owned_running',
      reason: null,
      bind: '127.0.0.1',
      port: listener.address().port,
    }],
  });
});

test('ensure keeps an existing listening service without spawning a replacement', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-ensure-existing-'));
  const listener = net.createServer();
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  const port = listener.address().port;
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [{
      id: 'existing',
      command: process.execPath,
      args: ['-e', 'process.exit(99)'],
      bind: '127.0.0.1',
      port,
      ensureProbe: { type: 'tcp' },
      shutdownOrder: 1,
      enabled: true,
    }],
  });
  t.after(async () => {
    await new Promise(resolve => listener.close(resolve));
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });

  const result = await supervisor.ensureAll();

  assert.equal(supervisor.children.size, 0);
  assert.deepEqual(result.map(item => ({ state: item.state, action: item.action, source: item.source })), [{
    state: 'ready',
    action: 'kept',
    source: 'existing',
  }]);
});

test('ensure starts missing services sequentially and continues after one fails', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-ensure-partial-'));
  const ports = [await reservePort(), await reservePort(), await reservePort()];
  const events = [];
  const listenerScript = [
    "const net = require('node:net');",
    "net.createServer(() => {}).listen(Number(process.env.TEST_PORT), '127.0.0.1');",
    'setInterval(() => {}, 60000);',
  ].join('');
  const services = [
    {
      id: 'first', command: process.execPath, args: ['-e', listenerScript],
      env: { TEST_PORT: String(ports[0]) }, bind: '127.0.0.1', port: ports[0],
      ensureProbe: { type: 'tcp' }, startTimeoutMs: 1000, shutdownOrder: 3, enabled: true,
    },
    {
      id: 'broken', command: process.execPath, args: ['-e', 'process.exit(7)'],
      bind: '127.0.0.1', port: ports[1], ensureProbe: { type: 'tcp' },
      startTimeoutMs: 500, shutdownOrder: 2, enabled: true,
    },
    {
      id: 'third', command: process.execPath, args: ['-e', listenerScript],
      env: { TEST_PORT: String(ports[2]) }, bind: '127.0.0.1', port: ports[2],
      ensureProbe: { type: 'tcp' }, startTimeoutMs: 1000, shutdownOrder: 1, enabled: true,
    },
  ];
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services,
    stopTimeoutMs: 1000,
    onEvent: event => events.push(event),
  });
  t.after(async () => {
    await supervisor.stopAll();
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });

  const result = await supervisor.ensureAll();

  assert.deepEqual(result.map(item => item.state), ['ready', 'failed', 'ready']);
  assert.deepEqual(result.map(item => item.action), ['started', 'start_failed', 'started']);
  assert.deepEqual(events.map(event => event.serviceId), ['first', 'third']);
  assert.match(result[1].reason, /service exited with code 7/);
  assert.ok(result[1].logs.stderr.endsWith('broken.stderr.log'));
});

test('ensure reports an occupied port with the wrong HTTP identity without killing it', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-ensure-identity-'));
  const listener = require('node:http').createServer((request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ serviceId: 'something-else' }));
  });
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  const port = listener.address().port;
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [{
      id: 'expected', command: process.execPath, args: ['-e', 'process.exit(99)'],
      bind: '127.0.0.1', port,
      ensureProbe: { type: 'http-json', path: '/health', expect: { serviceId: 'expected' } },
      shutdownOrder: 1, enabled: true,
    }],
  });
  t.after(async () => {
    await new Promise(resolve => listener.close(resolve));
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });

  const result = await supervisor.ensureAll();

  assert.equal(supervisor.children.size, 0);
  assert.equal(result[0].state, 'blocked_external');
  assert.equal(result[0].reason, 'health_identity_mismatch:serviceId');
});
