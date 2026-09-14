'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { WebSocketServer } = require('ws');
const { RobotExecutionClient } = require('../../../apps/orchestrator/src/robot-execution-client');

test('client shutdown rejects an in-flight Robot execution immediately', async (t) => {
  const server = http.createServer();
  const wss = new WebSocketServer({ server });
  let receivedResolve;
  const received = new Promise(resolve => { receivedResolve = resolve; });
  wss.on('connection', socket => socket.once('message', receivedResolve));
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  t.after(async () => {
    for (const socket of wss.clients) socket.terminate();
    await new Promise(resolve => wss.close(resolve));
    await new Promise(resolve => server.close(resolve));
  });
  const client = new RobotExecutionClient({
    url: `ws://127.0.0.1:${server.address().port}`,
    token: 'a'.repeat(64),
  });
  const operation = client.execute({
    primitiveId: 'pending-1',
    parameters: { timeoutMs: 30000 },
  });
  await received;
  client.close();
  const outcome = await Promise.race([
    operation.then(() => 'resolved', error => error.code),
    new Promise(resolve => setTimeout(() => resolve('timeout'), 300)),
  ]);
  assert.equal(outcome, 'client_closed');
});
