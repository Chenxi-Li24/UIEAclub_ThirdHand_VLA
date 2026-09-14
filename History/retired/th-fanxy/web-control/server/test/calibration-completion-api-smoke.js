'use strict';

const assert = require('assert/strict');
const express = require('express');
const {
  CalibrationCompletionService,
  createCalibrationCompletionRouter,
} = require('../calibration-completion-api');

function report(action = 'status', phase = 'handeye_collect', current = 0, required = 15) {
  return {
    schema_version: 1,
    ok: true,
    action,
    phase,
    progress: { current, required },
    sample: null,
    metrics: {
      relative: { validated: true },
      handeye: null,
      table: null,
      table_coverage: null,
    },
    remaining_blockers: ['handeye_samples_missing', 'table_validation_missing'],
    source_ids: {
      candidate: `sha256:${'1'.repeat(64)}`,
      relative_validation: `sha256:${'2'.repeat(64)}`,
      handeye: null,
      table: null,
    },
    safety: {
      robot_state_access: 'read_only_status',
      motion_command_access: false,
      executable: false,
    },
  };
}

function options(runProgram) {
  return {
    python: '/repo/.venv/bin/python',
    script: '/repo/scripts/vision/calibration_completion_workflow.py',
    candidate: '/repo/data/calibration/dual-camera-refit/candidate.json',
    relativeValidation: '/repo/data/calibration/relative.json',
    handeyeOutput: '/repo/data/calibration/handeye-current',
    handeyeResult: '/repo/data/calibration/handeye-current/result.json',
    tableOutput: '/repo/data/calibration/table-current',
    tableResult: '/repo/data/calibration/table-current/result.json',
    foundationOutput: '/repo/data/calibration/active-view-foundation',
    target: '/repo/configs/vision/calibration/charuco_12x9.yaml',
    d435Url: 'http://127.0.0.1:3100/camera_d435_raw',
    robotUrl: 'ws://127.0.0.1:3000/ws',
    cwd: '/repo',
    runProgram,
  };
}

async function listen(service, isLoopback = () => true) {
  const app = express();
  app.use('/api/calibration-completion', createCalibrationCompletionRouter({
    service,
    isLoopback,
  }));
  const server = await new Promise((resolve, reject) => {
    const candidate = app.listen(0, '127.0.0.1', () => resolve(candidate));
    candidate.once('error', reject);
  });
  return { server, baseUrl: `http://127.0.0.1:${server.address().port}` };
}

async function request(url, init) {
  const response = await fetch(url, init);
  return { status: response.status, body: await response.json() };
}

async function close(server) {
  await new Promise(resolve => server.close(resolve));
}

async function run() {
  const calls = [];
  const service = new CalibrationCompletionService(options(async invocation => {
    calls.push(invocation);
    const action = invocation.args[invocation.args.indexOf('--action') + 1];
    return {
      code: 0,
      stdout: JSON.stringify(report(
        action.replaceAll('-', '_'),
        action === 'capture-handeye' ? 'handeye_collect' : 'handeye_collect',
        action === 'capture-handeye' ? 1 : 0,
        15
      )),
      stderr: '',
    };
  }));
  const local = await listen(service);
  try {
    const status = await request(`${local.baseUrl}/api/calibration-completion/status`);
    assert.equal(status.status, 200);
    assert.equal(status.body.phase, 'handeye_collect');
    assert.equal(status.body.safety.motion_command_access, false);

    const crossOrigin = await request(
      `${local.baseUrl}/api/calibration-completion/status`,
      { headers: { origin: 'https://malicious.example' } }
    );
    assert.equal(crossOrigin.status, 403);
    assert.equal(crossOrigin.body.error.code, 'same_origin_required');

    const captured = await request(
      `${local.baseUrl}/api/calibration-completion/capture-handeye`,
      {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sample_id: 'injected', joints: [1, 2, 3] }),
      }
    );
    assert.equal(captured.status, 200);
    assert.equal(captured.body.action, 'capture_handeye');
    const call = calls.find(item => item.args.includes('capture-handeye'));
    assert.ok(call);
    assert.equal(call.command, '/repo/.venv/bin/python');
    assert.equal(call.args.includes('injected'), false);
    assert.equal(call.args.some(value => Array.isArray(value)), false);
    assert.equal(call.shell, undefined);
  } finally {
    await close(local.server);
  }

  const denied = await listen(service, () => false);
  try {
    const result = await request(`${denied.baseUrl}/api/calibration-completion/status`);
    assert.equal(result.status, 403);
    assert.equal(result.body.error.code, 'local_access_required');
  } finally {
    await close(denied.server);
  }

  const coverageService = new CalibrationCompletionService(options(async invocation => ({
    code: 0,
    stdout: JSON.stringify({
      ...report('status', 'table_collect', 8, 9),
      metrics: {
        relative: { validated: true },
        handeye: {
          position_rmse_m: 0.002,
          position_p95_m: 0.004,
          reprojection_rmse_px: 0.5,
        },
        table: null,
        table_coverage: {
          x_span_m: 0.0642,
          y_span_m: 0.1548,
          required_span_m: 0.10,
        },
      },
      remaining_blockers: ['table_xy_coverage_insufficient'],
    }),
    stderr: '',
  })));
  const coverage = await listen(coverageService);
  try {
    const result = await request(`${coverage.baseUrl}/api/calibration-completion/status`);
    assert.equal(result.status, 200);
    assert.deepEqual(result.body.metrics.table_coverage, {
      x_span_m: 0.0642,
      y_span_m: 0.1548,
      required_span_m: 0.10,
    });
  } finally {
    await close(coverage.server);
  }

  console.log('PASS calibration completion API is local, allowlisted, and coordinate-free');
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
