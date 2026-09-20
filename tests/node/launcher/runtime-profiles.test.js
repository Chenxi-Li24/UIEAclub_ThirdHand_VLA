'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const { loadServiceConfig } = require('../../../apps/launcher/src/service-config');

const ROOT = path.resolve(__dirname, '../../..');

function load(profile) {
  return loadServiceConfig(
    path.join(ROOT, 'configs', 'runtime', `${profile}.json`),
    { root: ROOT, nodePath: process.execPath },
  );
}

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

test('manual hardware profile never enables simulation or automatic motion', () => {
  const services = load('manual-control');
  const robot = services.find(item => item.id === 'robot');
  const web = services.find(item => item.id === 'web');

  assert.equal(robot.env.STARTOUCH_SIMULATE, '0');
  assert.equal(robot.env.STARTOUCH_CAN_INTERFACE, 'can0');
  assert.equal(robot.port, 3000);
  assert.equal(robot.args.length, 1);
  assert.equal(web.env.ROBOT_WS_URL, 'ws://127.0.0.1:3000/ws');
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
    ['robot', 'speech', 'vision', 'bottle-pick', 'web'],
  );

  const robot = services.find(item => item.id === 'robot');
  const speech = services.find(item => item.id === 'speech');
  const vision = services.find(item => item.id === 'vision');
  const bottlePick = services.find(item => item.id === 'bottle-pick');
  const web = services.find(item => item.id === 'web');
  assert.equal(speech.port, 3004);
  assert.equal(speech.bind, '127.0.0.1');
  assert.equal(
    speech.command,
    path.join(ROOT, 'services/speech/start-with-user-auth.sh'),
  );
  assert.equal(speech.args[0], path.join(ROOT, 'local/runtimes/python/bin/python'));
  assert.ok(speech.startTimeoutMs >= 120000);
  assert.equal(vision.port, 3100);
  assert.equal(vision.bind, '127.0.0.1');
  assert.equal(vision.args[0], path.join(ROOT, 'services/vision/src/server.js'));
  assert.equal(
    vision.env.VISION_PYTHON,
    path.join(ROOT, 'local/runtimes/vision-python/bin/python'),
  );
  assert.ok(vision.startTimeoutMs >= 30000);
  assert.equal(web.env.VOICE_WS_URL, 'ws://127.0.0.1:3004/v1/voice');
  assert.equal(web.env.VISION_HTTP_URL, 'http://127.0.0.1:3100');
  assert.equal(web.env.VISION_WS_URL, 'ws://127.0.0.1:3100/ws');
  assert.equal(web.env.VA_HTTP_URL, 'http://127.0.0.1:8766');
  assert.equal(bottlePick.port, 8766);
  assert.equal(bottlePick.bind, '127.0.0.1');
  assert.equal(
    bottlePick.env.THIRDHAND_VA_VISION_WS_URL,
    'ws://127.0.0.1:3100/ws',
  );
  assert.ok(web.shutdownOrder > bottlePick.shutdownOrder);
  assert.ok(web.shutdownOrder > vision.shutdownOrder);
  assert.ok(vision.shutdownOrder > services[0].shutdownOrder);
  assert.deepEqual(robot.ensureProbe.expect, { serviceId: 'robot' });
  assert.equal(speech.ensureProbe.type, 'tcp');
  assert.deepEqual(vision.ensureProbe.expect, { serviceId: 'vision' });
  assert.deepEqual(bottlePick.ensureProbe.expect, { status: 'ok' });
  assert.deepEqual(web.ensureProbe.expect, { serviceId: 'web' });
});
