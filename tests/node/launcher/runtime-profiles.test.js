'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadServiceConfig } = require('../../../apps/launcher/src/service-config');
const { resourcesForProfile } = require('../../../apps/launcher/src/cli');

const ROOT = path.resolve(__dirname, '../../..');

function load(profile) {
  return loadServiceConfig(
    path.join(ROOT, 'configs', 'runtime', `${profile}.json`),
    { root: ROOT, nodePath: process.execPath },
  );
}

test('gripper Plan simulation advertises only its simulated Startouch device', () => {
  assert.deepEqual(resourcesForProfile('gripper-plan-simulation', []), {
    services: {},
    devices: { startouch: 'ready' },
    models: {},
  });
});

test('manual simulation profile launches migrated robot and web services', () => {
  const services = load('manual-control-simulation');
  assert.deepEqual(services.map(item => item.id), ['robot', 'web']);

  const [robot, web] = services;
  assert.equal(robot.bind, '127.0.0.1');
  assert.equal(robot.port, 13000);
  assert.equal(robot.env.STARTOUCH_SIMULATE, '1');
  assert.equal(robot.args[0], path.join(ROOT, 'services/robot/src/server.js'));

  assert.equal(web.bind, '192.168.58.68');
  assert.equal(web.port, 9983);
  assert.equal(web.env.ROBOT_WS_URL, 'ws://127.0.0.1:13000/ws');
  assert.equal(web.args[0], path.join(ROOT, 'apps/web/src/server.js'));
});

test('gripper Plan simulation uses isolated ports and never opens CAN', () => {
  const services = load('gripper-plan-simulation');
  assert.deepEqual(services.map(item => item.id), ['robot', 'orchestrator', 'web']);
  const [robot, orchestrator, web] = services;
  assert.equal(robot.env.STARTOUCH_SIMULATE, '1');
  assert.equal(robot.env.STARTOUCH_REQUIRE_CAN_RX, '0');
  assert.equal(robot.port, 13000);
  assert.equal(orchestrator.port, 13200);
  assert.equal(orchestrator.env.ROBOT_EXECUTION_WS_URL, 'ws://127.0.0.1:13000/execution');
  assert.equal(web.port, 19983);
  assert.equal(web.env.ORCHESTRATOR_WS_URL, 'ws://127.0.0.1:13200/plan');
  assert.equal(web.env.VOICE_WS_URL, 'ws://127.0.0.1:3004/v1/voice');
  assert.equal(web.env.VISION_WS_URL, 'ws://127.0.0.1:3100/ws');
});

test('manual hardware profile never enables simulation or automatic motion', () => {
  const services = load('manual-control');
  const robot = services.find(item => item.id === 'robot');
  const orchestrator = services.find(item => item.id === 'orchestrator');
  const web = services.find(item => item.id === 'web');

  assert.equal(robot.env.STARTOUCH_SIMULATE, '0');
  assert.equal(robot.env.STARTOUCH_CAN_INTERFACE, 'can0');
  assert.equal(robot.port, 3000);
  assert.equal(robot.args.length, 1);
  assert.equal(robot.env.ROBOT_EXECUTION_TOKEN_FILE, path.join(ROOT, 'runtime/run/robot-execution.token'));
  assert.equal(orchestrator.bind, '127.0.0.1');
  assert.equal(orchestrator.port, 3200);
  assert.equal(orchestrator.env.ROBOT_EXECUTION_WS_URL, 'ws://127.0.0.1:3000/execution');
  assert.equal(web.env.ROBOT_WS_URL, 'ws://127.0.0.1:3000/ws');
  assert.equal(web.env.ORCHESTRATOR_WS_URL, 'ws://127.0.0.1:3200/plan');
});

test('default profile knows migrated entrypoints but keeps them disabled', () => {
  const services = load('default');
  const robot = services.find(item => item.id === 'robot');
  const web = services.find(item => item.id === 'web');

  assert.equal(robot.enabled, false);
  assert.equal(web.enabled, false);
  assert.equal(robot.args[0], path.join(ROOT, 'services/robot/src/server.js'));
  assert.equal(web.args[0], path.join(ROOT, 'apps/web/src/server.js'));
});
test('manual control starts internal services before the web gateway', () => {
  const services = load('manual-control').filter(item => item.enabled);
  assert.deepEqual(
    services.map(item => item.id),
    ['robot', 'speech', 'vision', 'orchestrator', 'web'],
  );

  const speech = services.find(item => item.id === 'speech');
  const vision = services.find(item => item.id === 'vision');
  const orchestrator = services.find(item => item.id === 'orchestrator');
  const web = services.find(item => item.id === 'web');
  assert.equal(speech.port, 3004);
  assert.equal(speech.bind, '127.0.0.1');
  assert.match(speech.command, /local\/runtimes\/python\/bin\/python$/);
  assert.ok(speech.startTimeoutMs >= 120000);
  assert.equal(vision.port, 3100);
  assert.equal(vision.bind, '127.0.0.1');
  assert.equal(vision.args[0], path.join(ROOT, 'services/vision/src/server.js'));
  assert.equal(
    vision.env.VISION_PYTHON,
    path.join(ROOT, 'local/runtimes/python/bin/python'),
  );
  assert.ok(vision.startTimeoutMs >= 30000);
  assert.equal(orchestrator.args[0], path.join(ROOT, 'apps/orchestrator/src/server.js'));
  assert.equal(orchestrator.env.ROBOT_HTTP_URL, 'http://127.0.0.1:3000');
  assert.equal(web.env.VOICE_WS_URL, 'ws://127.0.0.1:3004/v1/voice');
  assert.equal(web.env.VISION_HTTP_URL, 'http://127.0.0.1:3100');
  assert.equal(web.env.VISION_WS_URL, 'ws://127.0.0.1:3100/ws');
  assert.ok(web.shutdownOrder > vision.shutdownOrder);
  assert.ok(vision.shutdownOrder > services[0].shutdownOrder);
});
