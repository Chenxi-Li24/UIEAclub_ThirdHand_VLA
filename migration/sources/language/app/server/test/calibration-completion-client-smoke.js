'use strict';

const assert = require('assert/strict');
const { createCalibrationCompletionClient } = require('../../web/calibration-completion.js');

function element() {
  return {
    textContent: '',
    className: '',
    disabled: false,
    replaceChildren(...children) { this.children = children; },
  };
}

function report(phase, current, required) {
  return {
    schema_version: 1,
    ok: true,
    action: 'status',
    phase,
    progress: { current, required },
    sample: null,
    metrics: {
      relative: { validated: true },
      handeye: phase === 'handeye_collect' || phase === 'handeye_solve' ? null : {
        position_rmse_m: 0.002,
        position_p95_m: 0.004,
        reprojection_rmse_px: 0.5,
      },
      table: phase === 'foundation_validated' ? {
        fit_rmse_m: 0.001,
        validation_p95_m: 0.003,
      } : null,
      table_coverage: null,
    },
    remaining_blockers: phase === 'foundation_validated' ? [] : ['table_validation_missing'],
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

async function run() {
  const elements = Object.fromEntries([
    'primaryButton', 'result', 'phase', 'instruction', 'progressText', 'progressGrid',
    'sampleId', 'sampleSplit', 'samplePoints', 'sampleRmse', 'relativeStatus',
    'handeyeMetrics', 'tableMetrics', 'blockers',
  ].map(key => [key, element()]));
  const calls = [];
  let current = report('handeye_collect', 0, 15);
  const client = createCalibrationCompletionClient({
    elements,
    fetchJson: async (url, init) => {
      calls.push({ url, init });
      if (url.endsWith('capture-handeye')) current = report('handeye_collect', 1, 15);
      return current;
    },
    createProgressCell: element,
    schedule: () => 1,
    cancelSchedule: () => {},
    isVisible: () => true,
  });

  client.render(current);
  assert.equal(elements.primaryButton.textContent, '采集手眼姿态');
  assert.match(elements.instruction.textContent, /标定板保持固定/);
  assert.equal(elements.progressGrid.children.length, 15);

  const captured = await client.runPrimaryAction();
  assert.equal(captured.accepted, true);
  assert.equal(calls.at(-1).url, '/api/calibration-completion/capture-handeye');
  assert.equal(calls.at(-1).init.method, 'POST');

  client.render(report('table_collect', 0, 8));
  assert.equal(elements.primaryButton.textContent, '采集桌面位置');
  assert.match(elements.instruction.textContent, /平放/);

  const shortCoverage = report('table_collect', 8, 9);
  shortCoverage.metrics.table_coverage = {
    x_span_m: 0.0642,
    y_span_m: 0.1548,
    required_span_m: 0.10,
  };
  shortCoverage.remaining_blockers = ['table_xy_coverage_insufficient'];
  client.render(shortCoverage);
  assert.equal(elements.primaryButton.textContent, '补采桌面位置');
  assert.match(elements.instruction.textContent, /X 当前 64\.2 mm/);
  assert.match(elements.instruction.textContent, /还差 35\.8 mm/);
  assert.match(elements.blockers.textContent, /桌面 X\/Y 覆盖不足/);

  client.render(report('foundation_validated', 1, 1));
  assert.equal(elements.primaryButton.disabled, true);
  assert.match(elements.result.textContent, /几何基础已通过/);
  console.log('PASS calibration completion client follows the read-only artifact workflow');
}

run().catch(error => {
  console.error(`FAIL ${error.stack || error.message}`);
  process.exitCode = 1;
});
