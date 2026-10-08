#!/usr/bin/env node
'use strict';

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const baseUrl = (dependencies.baseUrl || process.env.THIRDHAND_VA_URL ||
    'http://127.0.0.1:8766').replace(/\/+$/, '');
  let path;
  if (argv.length === 1 && argv[0] === 'status') {
    path = '/api/va/test/status';
  } else if (argv.length === 3 && argv[0] === 'preview' &&
      argv[1] === '--target-id' && /^[1-5]$/.test(argv[2])) {
    path = `/api/va/test/preview?target_id=${argv[2]}`;
  } else {
    writeError('usage: supervised_test_grasp.js preview --target-id 1..5 | status');
    return 2;
  }
  try {
    const response = await fetchImpl(`${baseUrl}${path}`, { method: 'GET' });
    const result = await response.json();
    write(JSON.stringify(result, null, 2));
    return response.ok ? 0 : 3;
  } catch (error) {
    writeError(`supervised test service unavailable: ${error.message || error}`);
    return 3;
  }
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; });
}

module.exports = { main };
