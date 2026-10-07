'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { loadConfig } = require('../../../apps/web/src/config');

test('Dummy selects its isolated runtime, supports legacy clones and explicit override', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dummy-runtime-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const env = { DUMMY_RESOURCE_ROOT: root };
  assert.equal(loadConfig(env).dummy.python, path.join(root, 'local/runtimes/vision-python/bin/python'));
  const python = path.join(root, 'local/runtimes/dummy-python/bin/python');
  fs.mkdirSync(path.dirname(python), { recursive: true });
  fs.writeFileSync(python, '');
  assert.equal(loadConfig(env).dummy.python, python);
  assert.equal(loadConfig({ ...env, DUMMY_PYTHON: '/custom/python' }).dummy.python, '/custom/python');
});
