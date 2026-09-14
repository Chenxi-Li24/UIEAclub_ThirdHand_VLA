const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { ServiceSupervisor } = require('../../../apps/launcher/src/service-supervisor');
const { processStartMarker } = require('../../../apps/launcher/src/service-supervisor');
const { readState, writeStateAtomic } = require('../../../apps/launcher/src/state-store');

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
