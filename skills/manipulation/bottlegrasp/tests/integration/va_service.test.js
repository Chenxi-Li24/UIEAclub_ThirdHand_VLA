'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const { createWebServer } = require('../../apps/bottle_pick/web_server');
const { OperatorController } = require(
  '../../src/thirdhand_va/action/operator/controller'
);

function post(port, path, body) {
  return new Promise((resolve, reject) => {
    const encoded = Buffer.from(JSON.stringify(body));
    const request = http.request({
      hostname: '127.0.0.1', port, path, method: 'POST',
      headers: { 'content-type': 'application/json', 'content-length': encoded.length },
    }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({
        status: response.statusCode,
        body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
      }));
    });
    request.on('error', reject);
    request.end(encoded);
  });
}

test('L API is stable-ID idempotent and never delegates closed_loop_pick', async () => {
  const robotMessages = [];
  let ready = true;
  const operator = new OperatorController({
    createWorkflow({ onFinish }) {
      return {
        start() { return { accepted: true }; },
        cancel() { onFinish({ ok: false, reason: 'stopped' }); return { accepted: true }; },
      };
    },
  });
  const app = createWebServer({
    host: '127.0.0.1', port: 0, operatorController: operator,
    cameraBridge: { ready: false, subscribeMjpeg() { return false; } },
    robotMessages,
    robotControlEnabled: true,
    robotReady: () => ready,
  });
  const address = await app.start();
  const command = {
    schema: 'thirdhand.va.command.v1', cmd: 'start',
    target_id: 2, request_id: 'req-2',
  };
  try {
    const first = await post(address.port, '/api/va/start', command);
    // A running arm is away from Home, but retrying the same request remains idempotent.
    ready = false;
    const duplicate = await post(address.port, '/api/va/start', command);
    const conflict = await post(address.port, '/api/va/start', {
      ...command, target_id: 3, request_id: 'req-3',
    });
    assert.equal(first.status, 202);
    assert.equal(first.body.target_id, 2);
    assert.equal(duplicate.status, 202);
    assert.equal(duplicate.body.duplicate, true);
    assert.equal(conflict.status, 409);
    assert.equal(robotMessages.some(message => message.cmd === 'closed_loop_pick'), false);
  } finally {
    await app.stop();
  }
});

test('default local workflow completes against the full-cycle memory fixture', () => {
  const root = path.resolve(__dirname, '../..');
  const completed = spawnSync(process.execPath, [
    'scripts/action/debug_workflow.js', '--target-id', '2',
    '--fixture', 'tests/fixtures/integration/full-cycle.json',
  ], { cwd: root, encoding: 'utf8' });

  assert.equal(completed.status, 0, completed.stderr);
  const report = JSON.parse(completed.stdout);
  assert.equal(report.result.ok, true);
  assert.equal(report.result.phase, 'complete');
  assert.equal(report.camera_commands[0].stable_id, 2);
  assert.equal(report.fake_robot_commands.some(
    command => command.cmd === 'closed_loop_pick'
  ), false);
  assert.deepEqual(report.robot_command_sources.slice(-9), [
    'grasp:open', 'grasp:final_approach', 'grasp:close', 'grasp:lift',
    'grasp:transfer', 'grasp:lower', 'grasp:release', 'grasp:retreat',
    'grasp:return_home',
  ]);
  assert.equal(report.robot_control_enabled, false);
});
