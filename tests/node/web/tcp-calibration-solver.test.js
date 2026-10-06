'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { runTcpSolver } = require('../../../apps/web/src/tcp-calibration/solver-adapter');

const ROOT = path.resolve(__dirname, '../../..');
const PYTHON = process.env.PYTHON || 'python';
const SOLVER = path.join(ROOT, 'tools/tcp_calibration/solve_tcp.py');
const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'tests/fixtures/tcp-calibration/reference-pivot.json'), 'utf8',
));
const THRESHOLDS = Object.freeze({
  fitRmsGreenM: 0.002,
  fitMaximumGreenM: 0.004,
  fitRmsMaximumM: 0.003,
  fitMaximumM: 0.005,
  validationMaximumM: 0.005,
});

function temporaryPython(t, source) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tcp-solver-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const filename = path.join(directory, 'child.py');
  fs.writeFileSync(filename, source);
  return filename;
}

test('valid solver JSON round trip returns the exact approved schema', async () => {
  const result = await runTcpSolver({
    python: PYTHON,
    script: SOLVER,
    request: { operation: 'solve', fit_samples: FIXTURE.fit_samples, thresholds: THRESHOLDS },
  });
  assert.equal(result.schema, 'thirdhand-tcp-pivot-solve-v1');
  assert.equal(result.accepted, true);
  assert.deepEqual(result.sample_ids, FIXTURE.fit_samples.map(sample => sample.id));
});

test('timeout terminates the solver and rejects without mutating input', async t => {
  const script = temporaryPython(t, 'import time\ntime.sleep(5)\n');
  const request = { operation: 'solve', session: { stage: 'collecting' } };
  const before = structuredClone(request);
  await assert.rejects(
    runTcpSolver({ python: PYTHON, script, request, timeoutMs: 25 }),
    error => error.code === 'solver_timeout',
  );
  assert.deepEqual(request, before);
});

test('output limit terminates an overproducing solver', async t => {
  const script = temporaryPython(t, 'print("x" * 10000)\n');
  await assert.rejects(
    runTcpSolver({ python: PYTHON, script, request: {}, maximumOutputBytes: 128 }),
    error => error.code === 'solver_output_too_large',
  );
});

test('nonzero exit is rejected with a stable code', async t => {
  const script = temporaryPython(t, 'raise SystemExit(7)\n');
  await assert.rejects(
    runTcpSolver({ python: PYTHON, script, request: {} }),
    error => error.code === 'solver_failed',
  );
});

test('malformed and non-finite JSON are rejected', async t => {
  for (const output of ['not-json', '{"schema":"thirdhand-tcp-pivot-solve-v1","x":NaN}']) {
    const script = temporaryPython(t, `print(${JSON.stringify(output)})\n`);
    await assert.rejects(
      runTcpSolver({ python: PYTHON, script, request: {} }),
      error => error.code === 'solver_response_invalid',
    );
  }
});

test('unexpected result schema is rejected', async t => {
  const script = temporaryPython(t, 'print("{\\"schema\\":\\"unknown-v1\\"}")\n');
  await assert.rejects(
    runTcpSolver({ python: PYTHON, script, request: {} }),
    error => error.code === 'solver_response_invalid',
  );
});
