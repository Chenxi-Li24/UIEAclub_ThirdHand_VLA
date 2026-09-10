'use strict';

const { randomUUID } = require('node:crypto');

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const requestIdFactory = dependencies.requestIdFactory || randomUUID;
  const baseUrl = dependencies.baseUrl || process.env.THIRDHAND_VA_URL ||
    'http://127.0.0.1:8766';
  const action = argv[0];
  if (!['start', 'stop'].includes(action)) {
    writeError('usage: node apps/bottle_pick/run.js {start <1..5>|stop}');
    return 2;
  }
  const targetId = action === 'start' ? Number(argv[1]) : null;
  if (action === 'start' && (!Number.isSafeInteger(targetId) || targetId < 1 || targetId > 5)) {
    writeError('target ID must be an integer within [1, 5]');
    return 2;
  }
  if (typeof fetchImpl !== 'function') {
    writeError('fetch implementation is unavailable');
    return 3;
  }
  const requestId = requestIdFactory();
  const body = action === 'start'
    ? {
      schema: 'thirdhand.va.command.v1', cmd: 'start',
      target_id: targetId, request_id: requestId,
    }
    : { schema: 'thirdhand.va.command.v1', cmd: 'stop', request_id: requestId };
  try {
    const response = await fetchImpl(`${baseUrl}/api/va/${action}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    write(JSON.stringify(result));
    return response.status >= 200 && response.status < 300 && result.accepted === true
      ? 0 : 2;
  } catch (error) {
    writeError(`VA service unavailable: ${error.message || error}`);
    return 3;
  }
}

if (require.main === module) main().then(code => { process.exitCode = code; });

module.exports = { main };
