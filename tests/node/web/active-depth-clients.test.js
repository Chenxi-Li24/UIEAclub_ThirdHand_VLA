'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { WebSocketServer } = require('ws');
const { ExecutionClient } = require('../../../apps/web/src/active-depth/execution-client');
const { VisionClient } = require('../../../apps/web/src/active-depth/vision-client');
const { loadConfig } = require('../../../apps/web/src/config');

function primitive(id = 'align-1') {
  return {
    schema: 'thirdhand.execution-primitive.v1', primitiveId: id,
    traceId: 'trace-1', taskId: 'active-depth:session-1',
    authorizationId: 'active-depth:session-1', planDigest: `sha256:${'a'.repeat(64)}`,
    operation: 'vision.align.step', parameters: {
      sessionId: 'session-1', stableId: 2, frameId: 41,
      evidenceId: `sha256:${'b'.repeat(64)}`, motionEpoch: 1,
      tier: 'wrist', wristExhausted: false,
      startJointsDeg: [0, 0, 0, 0, 0, 0], targetJointsDeg: [0, 0, 0, 0, 1, 0],
      timeoutMs: 300,
    },
  };
}

async function executionServer(onMessage) {
  const requests = [];
  const server = http.createServer();
  const wss = new WebSocketServer({ noServer: true });
  server.on('upgrade', (request, socket, head) => {
    requests.push(request);
    wss.handleUpgrade(request, socket, head, ws => wss.emit('connection', ws));
  });
  wss.on('connection', socket => socket.on('message', data => onMessage(socket, JSON.parse(data))));
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {
    requests, url: `ws://127.0.0.1:${server.address().port}/execution`,
    async close() {
      for (const client of wss.clients) client.terminate();
      await new Promise(resolve => wss.close(resolve));
      await new Promise(resolve => server.close(resolve));
    },
  };
}

function tokenFixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'active-depth-token-'));
  const tokenFile = path.join(directory, 'token');
  fs.writeFileSync(tokenFile, `${'c'.repeat(64)}\n`, { mode: 0o600 });
  return { directory, tokenFile };
}

test('ExecutionClient authenticates only in upgrade header and correlates terminal status', async (t) => {
  const seen = [];
  const server = await executionServer((socket, message) => {
    seen.push(message);
    if (message.type === 'execution.stop') return;
    socket.send(JSON.stringify({
      type: 'execution.status', status: 'accepted', primitiveId: message.primitiveId,
    }));
    socket.send(JSON.stringify({
      type: 'execution.status', status: 'completed', code: 'target_reached',
      primitiveId: message.primitiveId, sessionId: message.parameters.sessionId,
    }));
  });
  const fixture = tokenFixture();
  const client = new ExecutionClient({ endpoint: server.url, tokenFile: fixture.tokenFile });
  t.after(async () => { client.close(); await server.close(); fs.rmSync(fixture.directory, { recursive: true }); });

  const result = await client.execute(primitive());
  assert.equal(result.status, 'completed');
  assert.equal(server.requests[0].headers['x-thirdhand-execution-token'], 'c'.repeat(64));
  assert.doesNotMatch(JSON.stringify(seen), /c{64}/);
  assert.doesNotMatch(JSON.stringify(client.publicStatus()), /c{64}/);
});

test('ExecutionClient fails closed on mismatched IDs and timeout sends exact stop control', async (t) => {
  const seen = [];
  let behavior = 'mismatch';
  const server = await executionServer((socket, message) => {
    seen.push(message);
    if (message.type === 'execution.stop') return;
    if (behavior === 'mismatch') {
      socket.send(JSON.stringify({ type: 'execution.status', status: 'completed', primitiveId: 'other' }));
    }
  });
  const fixture = tokenFixture();
  const client = new ExecutionClient({ endpoint: server.url, tokenFile: fixture.tokenFile, timeoutMs: 80 });
  t.after(async () => { client.close(); await server.close(); fs.rmSync(fixture.directory, { recursive: true }); });

  await assert.rejects(client.execute(primitive()), error => error.code === 'execution_uncertain');
  behavior = 'timeout';
  await assert.rejects(client.execute(primitive('align-2')), error => error.code === 'execution_uncertain');
  const stop = seen.find(message => message.type === 'execution.stop');
  assert.deepEqual(stop, {
    schema: 'thirdhand.execution-control.v1', type: 'execution.stop',
    sessionId: 'session-1', reason: 'operator_stop',
  });
});

test('ExecutionClient stop waits for the correlated terminal acknowledgement', async (t) => {
  let activePrimitiveId = null;
  const server = await executionServer((socket, message) => {
    if (message.type === 'execution.stop') {
      setTimeout(() => socket.send(JSON.stringify({
        type: 'execution.status', status: 'interrupted', code: 'operator_stop',
        primitiveId: activePrimitiveId,
      })), 30);
      return;
    }
    activePrimitiveId = message.primitiveId;
    socket.send(JSON.stringify({ type: 'execution.status', status: 'accepted', primitiveId: activePrimitiveId }));
  });
  const fixture = tokenFixture();
  const client = new ExecutionClient({ endpoint: server.url, tokenFile: fixture.tokenFile, timeoutMs: 500 });
  t.after(async () => { client.close(); await server.close(); fs.rmSync(fixture.directory, { recursive: true }); });

  const execution = client.execute(primitive());
  while (activePrimitiveId === null) await new Promise(resolve => setTimeout(resolve, 2));
  const startedAt = Date.now();
  const stopped = await client.stop('session-1');
  assert.equal(stopped.status, 'interrupted');
  assert.ok(Date.now() - startedAt >= 20);
  assert.equal((await execution).status, 'interrupted');
});

test('VisionClient joins fresh observation and runtime evidence without using ownership flag', async (t) => {
  let frameId = 41;
  let selectedStableId = 2;
  const server = http.createServer((request, response) => {
    response.setHeader('content-type', 'application/json');
    if (request.url === '/api/vision/observation') {
      response.end(JSON.stringify({
        frameId, observedAtMs: Date.now(), selectedStableId,
        targets: [{ stable_id: 2, centroid_xy: [300, 220], depthM: null }],
        robotControlEnabled: false,
      }));
      return;
    }
    response.end(JSON.stringify({
      runtimeEvidence: { camera_mount_id: 'mount-1', registration_id: 'registration-1' },
      detection: { frame_id: frameId, evidence_id: `sha256:${'e'.repeat(64)}`, motion_epoch: 7 },
    }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const client = new VisionClient({ baseUrl: `http://127.0.0.1:${server.address().port}` });

  const first = await client.snapshot(2);
  assert.equal(first.observation.robotControlEnabled, false);
  assert.equal(first.runtimeEvidence.camera_mount_id, 'mount-1');
  assert.equal(first.observation.camera_mount_id, 'mount-1');
  assert.equal(first.observation.evidence_id, `sha256:${'e'.repeat(64)}`);
  assert.equal(first.observation.motion_epoch, 7);
  const duplicate = await client.snapshot(2);
  assert.equal(duplicate.observation.frameId, 41);
  frameId += 1;
  selectedStableId = 3;
  await assert.rejects(client.snapshot(2), error => error.code === 'vision_target_mismatch');
});

test('web configuration exposes only server-side execution and mount paths', () => {
  const config = loadConfig({
    ROBOT_EXECUTION_WS_URL: 'ws://127.0.0.1:3333/execution',
    ROBOT_EXECUTION_TOKEN_FILE: '/runtime/private.token',
    ACTIVE_DEPTH_MOUNT_FILE: '/runtime/mount.json',
  });
  assert.equal(config.robotExecutionWsUrl, 'ws://127.0.0.1:3333/execution');
  assert.equal(config.robotExecutionTokenFile, '/runtime/private.token');
  assert.equal(config.activeDepthMountFile, '/runtime/mount.json');
});
