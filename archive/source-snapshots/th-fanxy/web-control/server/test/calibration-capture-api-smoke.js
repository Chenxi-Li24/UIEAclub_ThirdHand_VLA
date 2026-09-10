'use strict';

const assert = require('assert/strict');
const express = require('express');
const {
  CalibrationCaptureService,
  createCalibrationCaptureRouter,
} = require('../calibration-capture-api');

function report({
  action = 'status',
  phase = 'fit_collect',
  current = 2,
  required = 12,
  purpose = 'fit',
  sample = null,
  fitMetrics = null,
} = {}) {
  return {
    schema_version: 1,
    ok: true,
    action,
    phase,
    progress: { current, required, purpose },
    sample,
    fit_metrics: fitMetrics,
    relative_extrinsic_validated: phase === 'relative_validated',
    remaining_blockers: phase === 'relative_validated'
      ? ['handeye_validation_missing', 'table_validation_missing']
      : [
          'relative_extrinsic_refit_missing',
          'handeye_validation_missing',
          'table_validation_missing',
        ],
    safety: { motion_or_robot_access: false, executable: false },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function serviceOptions(runProgram) {
  return {
    python: '/repo/.venv/bin/python',
    script: '/repo/scripts/vision/dual_camera_refit_workflow.py',
    fitOutput: '/repo/data/calibration/dual-camera-refit/fit',
    validationOutput: '/repo/data/calibration/dual-camera-refit/validation',
    candidateOutput: '/repo/data/calibration/dual-camera-refit/candidate.json',
    seed: '/repo/configs/vision/calibration/legacy_dual_camera_candidate.json',
    target: '/repo/configs/vision/calibration/charuco_12x9.yaml',
    lumosUrl: 'http://127.0.0.1:3001/frame_raw.jpg',
    d435Url: 'http://127.0.0.1:3100/camera_d435_raw',
    runProgram,
  };
}

async function listen(service, isLoopback = () => true) {
  const app = express();
  app.use('/api/calibration', createCalibrationCaptureRouter({ service, isLoopback }));
  const server = await new Promise((resolve, reject) => {
    const candidate = app.listen(0, '127.0.0.1', () => resolve(candidate));
    candidate.once('error', reject);
  });
  return { server, baseUrl: `http://127.0.0.1:${server.address().port}` };
}

async function close(server) {
  await new Promise(resolve => server.close(resolve));
}

async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  return { status: response.status, body: await response.json() };
}

async function run() {
  const calls = [];
  const operationGate = deferred();
  const operationStarted = deferred();
  const runProgram = async invocation => {
    calls.push(invocation);
    const action = invocation.args[invocation.args.indexOf('--action') + 1];
    if (action === 'status') {
      return { code: 0, stdout: JSON.stringify(report()), stderr: '' };
    }
    operationStarted.resolve();
    await operationGate.promise;
    const sample = {
      id: 'fit-03',
      purpose: 'fit',
      common_points: 87,
      d435_reprojection_rmse_px: 0.36,
      lumos_reprojection_median_px: null,
      lumos_reprojection_p95_px: 118.7,
      capture_skew_ms: 28.0,
      passes_pixel_gate: true,
    };
    return {
      code: 0,
      stdout: JSON.stringify(report({ action: 'capture_fit', current: 3, sample })),
      stderr: '',
    };
  };
  const service = new CalibrationCaptureService(serviceOptions(runProgram));
  const local = await listen(service);
  try {
    const status = await jsonRequest(`${local.baseUrl}/api/calibration/status`);
    assert.equal(status.status, 200);
    assert.equal(status.body.phase, 'fit_collect');
    assert.deepEqual(status.body.progress, { current: 2, required: 12, purpose: 'fit' });
    assert.deepEqual(status.body.safety, {
      motion_or_robot_access: false,
      executable: false,
    });

    const crossOrigin = await jsonRequest(`${local.baseUrl}/api/calibration/status`, {
      headers: { origin: 'https://malicious.example' },
    });
    assert.equal(crossOrigin.status, 403);
    assert.equal(crossOrigin.body.error.code, 'same_origin_required');

    const firstCapture = jsonRequest(`${local.baseUrl}/api/calibration/capture-fit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ output: '/tmp/attacker', sample_id: 'injected' }),
    });
    await operationStarted.promise;
    const concurrentSolve = await jsonRequest(`${local.baseUrl}/api/calibration/solve`, {
      method: 'POST',
    });
    assert.equal(concurrentSolve.status, 409);
    assert.equal(concurrentSolve.body.error.code, 'operation_in_progress');
    operationGate.resolve();

    const captured = await firstCapture;
    assert.equal(captured.status, 200);
    assert.equal(captured.body.sample.id, 'fit-03');
    const captureCall = calls.find(call => call.args.includes('capture-fit'));
    assert.ok(captureCall);
    assert.equal(captureCall.command, '/repo/.venv/bin/python');
    assert.equal(captureCall.timeoutMs, 15000);
    assert.equal(captureCall.args.includes('/tmp/attacker'), false);
    assert.equal(JSON.stringify(captured.body).includes('/repo/'), false);
  } finally {
    await close(local.server);
  }

  const solveCalls = [];
  const solveService = new CalibrationCaptureService(serviceOptions(async invocation => {
    solveCalls.push(invocation);
    const action = invocation.args[invocation.args.indexOf('--action') + 1];
    if (action === 'status') {
      return {
        code: 0,
        stdout: JSON.stringify(report({ phase: 'fit_ready', current: 12 })),
        stderr: '',
      };
    }
    return {
      code: 0,
      stdout: JSON.stringify(report({
        action: 'solve',
        phase: 'validation_collect',
        current: 0,
        required: 10,
        purpose: 'validation',
        fitMetrics: {
          samples: 12,
          corners: 900,
          median_px: 0.3,
          p95_px: 0.8,
          baseline_m: 0.057,
          rotation_deg: 1.8,
          nfev: 22,
        },
      })),
      stderr: '',
    };
  }));
  const solveLocal = await listen(solveService);
  try {
    const solved = await jsonRequest(`${solveLocal.baseUrl}/api/calibration/solve`, {
      method: 'POST',
    });
    assert.equal(solved.status, 200);
    assert.equal(solved.body.phase, 'validation_collect');
    assert.equal(solved.body.fit_metrics.p95_px, 0.8);
    const solveCall = solveCalls.find(call => call.args.includes('solve'));
    assert.equal(solveCall.timeoutMs, 60000);
  } finally {
    await close(solveLocal.server);
  }

  const denied = await listen(service, () => false);
  try {
    const response = await jsonRequest(`${denied.baseUrl}/api/calibration/status`);
    assert.equal(response.status, 403);
    assert.equal(response.body.error.code, 'local_access_required');
  } finally {
    await close(denied.server);
  }

  const rejectedService = new CalibrationCaptureService(serviceOptions(async () => ({
    code: 2,
    stdout: JSON.stringify({
      schema_version: 1,
      ok: false,
      error: { code: 'target_not_visible', message: 'internal path /secret' },
    }),
    stderr: '/repo/secret traceback',
  })));
  const rejected = await listen(rejectedService);
  try {
    const response = await jsonRequest(`${rejected.baseUrl}/api/calibration/status`);
    assert.equal(response.status, 422);
    assert.equal(response.body.error.code, 'target_not_visible');
    assert.equal(JSON.stringify(response.body).includes('/secret'), false);
  } finally {
    await close(rejected.server);
  }

  console.log('PASS calibration refit API is phased, local-only, bounded, and single-flight');
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
