const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');

const {
  CanInterfaceManager,
  needsFullProfileRecovery,
  parseCanLinkDetails,
} = require('../../../apps/launcher/src/can-interface');
const { ensureRuntime } = require('../../../apps/launcher/src/runtime-ensure');
const { loadRuntimeConfig } = require('../../../apps/launcher/src/service-config');

const ROOT = path.resolve(__dirname, '../../..');

const READY_CAN = `3: can0: <NOARP,UP,LOWER_UP,ECHO> mtu 16 state UP
    link/can
    can state ERROR-ACTIVE (berr-counter tx 0 rx 0) restart-ms 100
      bitrate 1000000 sample-point 0.750
    RX: bytes  packets  errors  dropped overrun mcast
    429232     53654    0       0       0       0
    TX: bytes  packets  errors  dropped carrier collsns
    429272     53659    0       0       0       0
`;

const DOWN_CAN = `3: can0: <NOARP,ECHO> mtu 16 state DOWN
    link/can
    can state STOPPED (berr-counter tx 0 rx 0) restart-ms 0
      bitrate 500000 sample-point 0.875
    RX: bytes  packets  errors  dropped overrun mcast
    0          0        0       0       0       0
    TX: bytes  packets  errors  dropped carrier collsns
    720        90       0       0       0       0
`;

const FRESH_DOWN_CAN = DOWN_CAN.replace(
  '720        90       0       0       0       0',
  '0          0        0       0       0       0',
);

test('parses the SocketCAN state needed for one-click recovery decisions', () => {
  assert.deepEqual(parseCanLinkDetails(READY_CAN, {
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
  }), {
    interface: 'can0', exists: true, up: true, state: 'ERROR-ACTIVE',
    bitrate: 1000000, restartMs: 100, rxPackets: 53654, txPackets: 53659,
    ready: true,
  });
});

test('manual-control profile enables guarded CAN preparation without SDK auto-connect', () => {
  const runtime = loadRuntimeConfig(
    path.join(ROOT, 'configs/runtime/manual-control.json'),
    { root: ROOT, nodePath: process.execPath },
  );

  assert.deepEqual(runtime.can, {
    enabled: true,
    interface: 'can0',
    bitrate: 1000000,
    restartMs: 100,
  });
  assert.equal(runtime.services.find(item => item.id === 'robot').env.STARTOUCH_CAN_INTERFACE, 'can0');
});

test('keeps a correctly configured CAN interface without changing it', async () => {
  const calls = [];
  const manager = new CanInterfaceManager({
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
    run(command, args) {
      calls.push([command, ...args]);
      return { status: 0, stdout: READY_CAN, stderr: '' };
    },
  });

  const result = await manager.ensure();

  assert.equal(result.state, 'ready');
  assert.equal(result.action, 'kept');
  assert.deepEqual(calls, [['ip', '-details', '-statistics', 'link', 'show', 'can0']]);
});

test('reconfigures a down CAN interface with the teammate recovery settings', async () => {
  const calls = [];
  const inspections = [FRESH_DOWN_CAN, READY_CAN];
  const manager = new CanInterfaceManager({
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
    run(command, args) {
      calls.push([command, ...args]);
      if (command === 'ip') return { status: 0, stdout: inspections.shift(), stderr: '' };
      return { status: 0, stdout: '', stderr: '' };
    },
  });

  const result = await manager.ensure();

  assert.equal(result.state, 'ready');
  assert.equal(result.action, 'reconfigured');
  assert.deepEqual(calls, [
    ['ip', '-details', '-statistics', 'link', 'show', 'can0'],
    ['sudo', '-n', 'ip', 'link', 'set', 'can0', 'down'],
    ['sudo', '-n', 'ip', 'link', 'set', 'can0', 'type', 'can', 'bitrate', '1000000', 'restart-ms', '100'],
    ['sudo', '-n', 'ip', 'link', 'set', 'can0', 'up'],
    ['ip', '-details', '-statistics', 'link', 'show', 'can0'],
  ]);
});

test('reports a missing CAN adapter without pretending it is ready', async () => {
  const manager = new CanInterfaceManager({
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
    run() {
      return { status: 1, stdout: '', stderr: 'Device "can0" does not exist.' };
    },
  });

  const result = await manager.ensure();

  assert.equal(result.state, 'failed');
  assert.equal(result.action, 'blocked');
  assert.equal(result.reason, 'can_interface_missing');
});

test('uses full profile recovery only for stale or one-way CAN conditions', () => {
  const ready = parseCanLinkDetails(READY_CAN, {
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
  });
  const down = parseCanLinkDetails(DOWN_CAN, {
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
  });
  const freshDown = parseCanLinkDetails(FRESH_DOWN_CAN, {
    interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
  });

  assert.equal(needsFullProfileRecovery(ready, { robotServiceReady: true }), false);
  assert.equal(needsFullProfileRecovery(freshDown, { robotServiceReady: false }), false);
  assert.equal(needsFullProfileRecovery(down, { robotServiceReady: false }), true);
  assert.equal(needsFullProfileRecovery(down, { robotServiceReady: true }), true);
  assert.equal(needsFullProfileRecovery({ ...ready, rxPackets: 0, txPackets: 90 }, {
    robotServiceReady: false,
  }), true);
});

test('extreme recovery stops the profile, repairs CAN, then restores services without connecting SDK', async () => {
  const events = [];
  const services = [{ id: 'robot', enabled: true }];
  const canManager = {
    async inspect() {
      events.push('can.inspect');
      return parseCanLinkDetails(DOWN_CAN, {
        interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
      });
    },
    async ensure() {
      events.push('can.ensure');
      return { state: 'ready', action: 'reconfigured', interface: 'can0' };
    },
  };
  const serviceSupervisor = {
    async stopAll() {
      events.push('services.stop');
      return [{ id: 'robot', state: 'stopped' }];
    },
    async ensureAll() {
      events.push('services.ensure');
      return [{ id: 'robot', state: 'ready', action: 'started' }];
    },
  };

  const result = await ensureRuntime({
    canManager,
    serviceSupervisor,
    services,
    probeService: async () => ({ ready: true }),
  });

  assert.equal(result.recoveryMode, 'full-profile');
  assert.deepEqual(events, ['can.inspect', 'services.stop', 'can.ensure', 'services.ensure']);
  assert.deepEqual(result.services, [{ id: 'robot', state: 'ready', action: 'started' }]);
});

test('normal recovery repairs CAN before filling missing services', async () => {
  const events = [];
  const result = await ensureRuntime({
    canManager: {
      async inspect() {
        events.push('can.inspect');
        return parseCanLinkDetails(FRESH_DOWN_CAN, {
          interfaceName: 'can0', bitrate: 1000000, restartMs: 100,
        });
      },
      async ensure() {
        events.push('can.ensure');
        return { state: 'ready', action: 'reconfigured', interface: 'can0' };
      },
    },
    serviceSupervisor: {
      async stopAll() {
        events.push('services.stop');
        return [];
      },
      async ensureAll() {
        events.push('services.ensure');
        return [{ id: 'robot', state: 'ready', action: 'started' }];
      },
    },
    services: [{ id: 'robot', enabled: true }],
    probeService: async () => ({ ready: false }),
  });

  assert.equal(result.recoveryMode, 'can-only');
  assert.deepEqual(events, ['can.inspect', 'can.ensure', 'services.ensure']);
});
