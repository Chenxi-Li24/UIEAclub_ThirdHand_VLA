'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const root = path.resolve(__dirname, '../../..');

test('fixed TCP button is retained when the preset grid is rebuilt', () => {
  const html = fs.readFileSync(path.join(root, 'apps/web/public/index.html'), 'utf8');
  const script = fs.readFileSync(path.join(root, 'apps/web/public/js/main.js'), 'utf8');
  assert.match(html, /id="btn-fixed-tcp-demo"/);
  assert.match(script, /if \(demoButton\) grid\.appendChild\(demoButton\)/);
  assert.match(script, /cmd: 'fixed_tcp_demo'/);
});

test('web gateway treats a fixed TCP command as controlled motion', () => {
  const script = fs.readFileSync(path.join(root, 'apps/web/src/robot-proxy.js'), 'utf8');
  assert.match(script, /'fixed_tcp_demo'/);
  assert.match(script, /'gripper',\s*'fixed_tcp_demo'\]\s*\.includes\(message\.cmd\)/);
});
