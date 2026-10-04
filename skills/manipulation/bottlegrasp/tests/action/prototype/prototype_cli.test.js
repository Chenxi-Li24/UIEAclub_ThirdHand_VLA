'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname,'../../..');
const script = 'scripts/action/prototype_grasp_validation.js';
const fixture = 'tests/fixtures/action/prototype-grasp.json';
function run(args) { return spawnSync(process.execPath,[script,...args],{cwd:root,encoding:'utf8',timeout:5000}); }

test('CLI produces a deterministic four-phase simulated report', () => {
  const result = run(['--fixture',fixture]);
  assert.equal(result.status,0,result.stderr);
  assert.equal(result.stderr,'');
  const report = JSON.parse(result.stdout);
  assert.equal(report.schema,'thirdhand-prototype-grasp-report-v1');
  assert.equal(report.status,'complete');
  assert.equal(report.simulationOnly,true);
  assert.deepEqual(report.commands.map(command => command.request_id),
    ['prototype-1:pregrasp','prototype-1:approach','prototype-1:grip','prototype-1:lift']);
  assert.equal(report.finalState.completedPhases,4);
  assert.equal(run(['--fixture',fixture]).stdout,result.stdout);
});

test('CLI rejects hardware options before accessing fixture', () => {
  for (const option of ['--execute','--real','--backend','--can','--socket','--real=true']) {
    const result = run(['--fixture','missing.json',option]);
    assert.equal(result.status,2);
    assert.equal(result.stdout,'');
    assert.equal(JSON.parse(result.stderr).error,'prototype_hardware_option_forbidden');
  }
});

test('CLI reports missing duplicate and unknown arguments as structured errors', () => {
  for (const args of [[], ['--fixture'],['--unknown'],['--fixture',fixture,'--fixture',fixture]]) {
    const result = run(args);
    assert.equal(result.status,2);
    assert.equal(JSON.parse(result.stderr).error,'prototype_arguments_invalid');
  }
  const missing = run(['--fixture','missing.json']);
  assert.equal(missing.status,2);
  assert.equal(JSON.parse(missing.stderr).error,'prototype_fixture_invalid');
});

test('prototype source has no hardware or production execution imports', () => {
  const directory = path.join(root,'src/thirdhand_va/action/prototype');
  const files = fs.readdirSync(directory).filter(file => file.endsWith('.js')).map(file => path.join(directory,file));
  files.push(path.join(root,script));
  for (const file of files) {
    assert.doesNotMatch(fs.readFileSync(file,'utf8'),
      /startouch|robot_ws_client|robot_client_factory|execution_gate|workflow|ws:\/\/|can0|child_process/i,file);
  }
});
