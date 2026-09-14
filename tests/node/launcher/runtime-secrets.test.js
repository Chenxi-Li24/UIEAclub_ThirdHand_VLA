'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  prepareExecutionToken,
  removeExecutionToken,
} = require('../../../apps/launcher/src/runtime-secrets');
const { ServiceSupervisor, processStartMarker } = require('../../../apps/launcher/src/service-supervisor');

function tokenService(runtimeDir, id = 'robot', args = null) {
  return {
    id,
    command: process.execPath,
    args: args || [path.resolve('tools/fixtures/fake_service.js')],
    cwd: process.cwd(),
    env: { ROBOT_EXECUTION_TOKEN_FILE: path.join(runtimeDir, 'run', 'robot-execution.token') },
    shutdownOrder: 10,
    enabled: true,
  };
}

test('execution token is random lowercase hex, owner-only, atomic, and reusable', () => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-secret-'));
  try {
    const first = prepareExecutionToken({ runtimeDir });
    const firstValue = fs.readFileSync(first.path, 'utf8').trim();
    assert.match(firstValue, /^[0-9a-f]{64}$/);
    assert.equal(first.created, true);
    if (process.platform !== 'win32') {
      assert.equal(fs.statSync(first.path).mode & 0o777, 0o600);
    }
    assert.equal(fs.readdirSync(path.dirname(first.path)).some(name => name.endsWith('.tmp')), false);

    const reused = prepareExecutionToken({ runtimeDir });
    assert.equal(reused.created, false);
    assert.equal(fs.readFileSync(reused.path, 'utf8').trim(), firstValue);
    removeExecutionToken({ runtimeDir });
    assert.equal(fs.existsSync(first.path), false);
  } finally {
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  }
});

test('supervisor reuses a token while owned services run and rotates after clean stop', async (t) => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-secret-run-'));
  const events = [];
  const supervisor = new ServiceSupervisor({
    runtimeDir,
    services: [tokenService(runtimeDir)],
    onEvent: event => events.push(event),
  });
  t.after(async () => {
    await supervisor.stopAll();
    fs.rmSync(runtimeDir, { recursive: true, force: true });
  });
  const tokenPath = path.join(runtimeDir, 'run', 'robot-execution.token');

  await supervisor.startAll();
  const firstValue = fs.readFileSync(tokenPath, 'utf8').trim();
  await supervisor.startAll();
  assert.equal(fs.readFileSync(tokenPath, 'utf8').trim(), firstValue);
  assert.doesNotMatch(JSON.stringify(events), new RegExp(firstValue));

  await supervisor.stopAll();
  assert.equal(fs.existsSync(tokenPath), false);
  await supervisor.startAll();
  const secondValue = fs.readFileSync(tokenPath, 'utf8').trim();
  assert.notEqual(secondValue, firstValue);
});

test('failed group startup stops earlier owned children and removes its new token', async () => {
  const runtimeDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-secret-fail-'));
  const robot = tokenService(runtimeDir);
  const failing = {
    ...tokenService(runtimeDir, 'failing', ['-e', 'setInterval(() => {}, 60000)']),
    shutdownOrder: 20,
    startTimeoutMs: 75,
  };
  const supervisor = new ServiceSupervisor({ runtimeDir, services: [robot, failing], stopTimeoutMs: 500 });

  await assert.rejects(supervisor.startAll(), /readiness timeout/);
  const robotChild = supervisor.children.get('robot');
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(processStartMarker(robotChild.pid), null);
  assert.equal(fs.existsSync(path.join(runtimeDir, 'run', 'robot-execution.token')), false);
  fs.rmSync(runtimeDir, { recursive: true, force: true });
});
