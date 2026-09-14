'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const { probeTcpPort } = require('../../../apps/launcher/src/service-supervisor');

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
}

function close(server) {
  return new Promise(resolve => server.close(resolve));
}

test('reports a listening TCP endpoint as occupied', async (t) => {
  const server = net.createServer();
  await listen(server);
  t.after(() => close(server));

  assert.deepEqual(
    await probeTcpPort({ host: '127.0.0.1', port: server.address().port }),
    { occupied: true, errorCode: null },
  );
});

test('reports a closed TCP endpoint as available', async () => {
  const server = net.createServer();
  await listen(server);
  const port = server.address().port;
  await close(server);

  assert.deepEqual(
    await probeTcpPort({ host: '127.0.0.1', port }),
    { occupied: false, errorCode: null },
  );
});
