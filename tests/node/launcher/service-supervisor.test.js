const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { ServiceSupervisor } = require('../../../apps/launcher/src/service-supervisor');

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
