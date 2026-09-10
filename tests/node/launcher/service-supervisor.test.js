const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
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
