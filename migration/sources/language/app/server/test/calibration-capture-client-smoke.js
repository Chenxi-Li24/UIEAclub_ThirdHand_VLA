'use strict';

const assert = require('assert/strict');
const { createCalibrationCaptureClient } = require('../../web/calibration-capture');

function element() {
  return {
    textContent: '',
    className: '',
    disabled: false,
    children: [],
    replaceChildren(...children) { this.children = children; },
  };
}

function elements() {
  return {
    captureButton: element(),
    result: element(),
    phaseLabel: element(),
    progressPurpose: element(),
    progressText: element(),
    progressGrid: element(),
    sampleId: element(),
    commonPoints: element(),
    d435Rmse: element(),
    lumosP95: element(),
    captureSkew: element(),
    fitMedian: element(),
    fitP95: element(),
    fitBaseline: element(),
    fitRotation: element(),
    validation: element(),
    blockers: element(),
  };
}

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

function sample(id, purpose) {
  return {
    id,
    purpose,
    common_points: 87,
    d435_reprojection_rmse_px: 0.36,
    lumos_reprojection_median_px: purpose === 'validation' ? 0.4 : null,
    lumos_reprojection_p95_px: purpose === 'validation' ? 0.9 : 118.7,
    capture_skew_ms: 28.0,
    passes_pixel_gate: true,
  };
}

function fitMetrics() {
  return {
    samples: 12,
    corners: 980,
    median_px: 0.24,
    p95_px: 0.82,
    baseline_m: 0.0572,
    rotation_deg: 1.83,
    nfev: 22,
  };
}

async function run() {
  const ui = elements();
  const calls = [];
  let nextPostReport = report({
    action: 'capture_fit',
    current: 3,
    sample: sample('fit-03', 'fit'),
  });
  const client = createCalibrationCaptureClient({
    elements: ui,
    fetchJson: async (url, options = {}) => {
      calls.push({ url, options });
      return options.method === 'POST' ? nextPostReport : report();
    },
    createProgressCell: () => element(),
    schedule: () => 1,
    cancelSchedule: () => {},
    isVisible: () => true,
  });

  client.render(report());
  assert.equal(ui.phaseLabel.textContent, '阶段 1 / 3 · 采集拟合姿态');
  assert.equal(ui.captureButton.textContent, '采集拟合姿态');
  assert.equal(ui.progressText.textContent, '2 / 12');
  assert.equal(ui.progressGrid.children.length, 12);
  await client.runPrimaryAction();
  assert.equal(calls.at(-1).url, '/api/calibration/capture-fit');
  assert.equal(ui.sampleId.textContent, 'fit-03');
  assert.equal(ui.lumosP95.textContent, '118.700 px（旧外参诊断）');

  client.render(report({ phase: 'fit_ready', current: 12 }));
  assert.equal(ui.phaseLabel.textContent, '阶段 2 / 3 · 求解新外参');
  assert.equal(ui.captureButton.textContent, '求解新外参');
  nextPostReport = report({
    action: 'solve',
    phase: 'validation_collect',
    current: 0,
    required: 10,
    purpose: 'validation',
    fitMetrics: fitMetrics(),
  });
  await client.runPrimaryAction();
  assert.equal(calls.at(-1).url, '/api/calibration/solve');
  assert.equal(ui.fitP95.textContent, '0.820 px');
  assert.equal(ui.fitBaseline.textContent, '57.2 mm');

  client.render(report({
    phase: 'validation_collect',
    current: 2,
    required: 10,
    purpose: 'validation',
    fitMetrics: fitMetrics(),
  }));
  assert.equal(ui.phaseLabel.textContent, '阶段 3 / 3 · 独立验证');
  assert.equal(ui.captureButton.textContent, '采集验证姿态');
  nextPostReport = report({
    action: 'capture_validation',
    phase: 'validation_collect',
    current: 3,
    required: 10,
    purpose: 'validation',
    sample: sample('pose-03', 'validation'),
    fitMetrics: fitMetrics(),
  });
  await client.runPrimaryAction();
  assert.equal(calls.at(-1).url, '/api/calibration/capture');
  assert.equal(ui.lumosP95.textContent, '0.900 px');

  client.render(report({
    phase: 'relative_validated',
    current: 10,
    required: 10,
    purpose: 'validation',
    sample: sample('pose-10', 'validation'),
    fitMetrics: fitMetrics(),
  }));
  assert.equal(ui.captureButton.disabled, true);
  assert.match(ui.validation.textContent, /外参独立验证通过/);
  assert.match(ui.result.textContent, /不能执行抓取/);

  const rejectedUi = elements();
  const rejectedClient = createCalibrationCaptureClient({
    elements: rejectedUi,
    fetchJson: async () => {
      const error = new Error('rejected');
      error.code = 'pose_not_distinct';
      throw error;
    },
    createProgressCell: () => element(),
    schedule: () => 2,
    cancelSchedule: () => {},
    isVisible: () => true,
  });
  rejectedClient.render(report());
  await rejectedClient.runPrimaryAction();
  assert.match(rejectedUi.result.textContent, /移动至少 15 mm|倾斜至少 3°/);

  client.destroy();
  rejectedClient.destroy();
  console.log('PASS calibration client drives fit, solve, validation, and completion phases');
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
