'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { WebSocketServer } = require('ws');

async function main() {
  const received = [];
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise(resolve => server.once('listening', resolve));
  const port = server.address().port;
  server.on('connection', socket => {
    socket.on('message', payload => {
      received.push(JSON.parse(payload.toString()));
      socket.send(JSON.stringify({
        type: 'robot_state',
        joints: [1, 20, -40, 0, 10, 0],
        velocities: [0, 0, 0, 0, 0, 0],
        tcpPos: [100, 20, 500],
        tcpEuler: [0, 0, 90],
        stateName: 'idle',
        ts: Date.now(),
      }));
    });
  });

  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'active-view-teach-'));
  const output = path.join(directory, 'captures.json');
  const script = path.resolve(__dirname, '../../scripts/teach-active-view-pose.js');
  const child = spawn(process.execPath, [
    script,
    '--name', 'table_center',
    '--server', `ws://127.0.0.1:${port}`,
    '--output', output,
  ], { stdio: ['ignore', 'pipe', 'pipe'] });
  let stderr = '';
  child.stderr.on('data', chunk => { stderr += chunk; });
  const exitCode = await new Promise(resolve => child.once('exit', resolve));
  server.close();

  assert.equal(exitCode, 0, stderr);
  assert.deepEqual(received, [{ cmd: 'status' }]);
  const saved = JSON.parse(fs.readFileSync(output, 'utf8'));
  assert.equal(saved.schema_version, 1);
  assert.equal(saved.captures.length, 1);
  assert.equal(saved.captures[0].name, 'table_center');
  assert.deepEqual(saved.captures[0].joints_deg, [1, 20, -40, 0, 10, 0]);
  assert.deepEqual(saved.captures[0].tcp_position_m, [0.1, 0.02, 0.5]);
  assert(Math.abs(saved.captures[0].tcp_euler_rad[2] - Math.PI / 2) < 1e-12);
  const serialized = JSON.stringify(saved).toLowerCase();
  for (const forbidden of ['move_joint', 'move_l', 'servo', 'preset', 'gripper', 'grasp']) {
    assert.equal(serialized.includes(forbidden), false);
    assert.equal(JSON.stringify(received).toLowerCase().includes(forbidden), false);
  }
  console.log('PASS active-view pose teaching is read-only and atomic');
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
