'use strict';

(function expose(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandCalibrationCompletion = api;
}(typeof globalThis === 'object' ? globalThis : this, function build(root) {
  const PHASES = Object.freeze({
    handeye_collect: {
      label: '阶段 1 / 4 · 采集 15 个手眼姿态',
      button: '采集手眼姿态',
      endpoint: '/api/calibration-completion/capture-handeye',
      working: '正在读取 D435 帧和三次稳定机械臂状态…',
      instruction: '标定板保持固定。手动把机械臂调整到一个明显不同的视角，完全停稳后点击；每次只采一个姿态。',
    },
    handeye_solve: {
      label: '阶段 2 / 4 · 求解并留出验证手眼外参',
      button: '求解手眼外参',
      endpoint: '/api/calibration-completion/solve-handeye',
      working: '正在比较 PARK、TSAI、HORAUD，并只用留出样本决定是否通过…',
      instruction: '15 个姿态已齐。标定板继续保持固定，点击求解；这个步骤不采图、不运动。',
    },
    table_collect: {
      label: '阶段 3 / 4 · 采集桌面位置（至少 8 个）',
      button: '采集桌面位置',
      endpoint: '/api/calibration-completion/capture-table',
      working: '正在采集平放标定板并换算到机械臂基座坐标系…',
      instruction: '把标定板平放在桌面，每次沿 X/Y 明显换一个位置（总跨度至少各 10 cm），停稳后点击。',
    },
    finalize: {
      label: '阶段 4 / 4 · 验证桌面并生成运行时证据',
      button: '验证并生成证据',
      endpoint: '/api/calibration-completion/finalize',
      working: '正在用 6 个拟合样本与 2 个留出样本验证桌面，并做运行时往返加载…',
      instruction: '8 个桌面位置已齐。保持现场不动，点击生成最终 camera.json 与 table.json。',
    },
    foundation_validated: {
      label: '完成 · 主动视觉几何基础通过',
      button: '标定已完成',
      endpoint: null,
      working: '',
      instruction: '相机链、手眼外参和桌面平面都已通过独立验证；真实运动与抓取仍保持关闭。',
    },
  });
  const KEYS = [
    'primaryButton', 'result', 'phase', 'instruction', 'progressText', 'progressGrid',
    'sampleId', 'sampleSplit', 'samplePoints', 'sampleRmse', 'relativeStatus',
    'handeyeMetrics', 'tableMetrics', 'blockers',
  ];

  function requireElements(value) {
    if (!value || typeof value !== 'object') throw new TypeError('elements are required');
    for (const key of KEYS) if (!value[key]) throw new TypeError(`elements.${key} is required`);
    return value;
  }

  function metric(value, scale = 1, digits = 3, suffix = '') {
    return typeof value === 'number' && Number.isFinite(value)
      ? `${(value * scale).toFixed(digits)}${suffix}` : '—';
  }

  function blockerText(items) {
    const labels = {
      handeye_samples_missing: '手眼姿态未采满',
      handeye_validation_missing: '手眼外参待验证',
      table_samples_missing: '桌面位置未采满',
      table_validation_missing: '桌面平面待验证',
      table_xy_coverage_insufficient: '桌面 X/Y 覆盖不足',
      foundation_not_finalized: '运行时证据待生成',
    };
    return Array.isArray(items) && items.length
      ? items.map(item => labels[item] || item).join(' · ') : '无';
  }

  function createCalibrationCompletionClient(options = {}) {
    const elements = requireElements(options.elements);
    const fetchJson = options.fetchJson;
    const createProgressCell = options.createProgressCell;
    const schedule = options.schedule;
    const cancelSchedule = options.cancelSchedule;
    const isVisible = options.isVisible;
    for (const [name, value] of Object.entries({
      fetchJson, createProgressCell, schedule, cancelSchedule, isVisible,
    })) if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    let phase = 'handeye_collect';
    let busy = false;
    let destroyed = false;
    let timer = null;
    let polling = false;

    function buttonState() {
      elements.primaryButton.disabled = destroyed || busy || !PHASES[phase]?.endpoint;
    }

    function render(report) {
      if (!report || report.ok !== true || !PHASES[report.phase]) {
        throw new TypeError('completion report is invalid');
      }
      const current = report.progress?.current;
      const required = report.progress?.required;
      if (!Number.isInteger(current) || !Number.isInteger(required) || required < 1 || current > required) {
        throw new TypeError('completion progress is invalid');
      }
      phase = report.phase;
      const config = PHASES[phase];
      elements.phase.textContent = config.label;
      const coverage = report.metrics?.table_coverage;
      const supplementingTable = phase === 'table_collect' && current >= 8 && coverage;
      if (supplementingTable) {
        const requiredMm = coverage.required_span_m * 1000;
        const xMm = coverage.x_span_m * 1000;
        const yMm = coverage.y_span_m * 1000;
        const shortAxes = [];
        if (xMm < requiredMm) shortAxes.push(`X 当前 ${xMm.toFixed(1)} mm，还差 ${(requiredMm - xMm).toFixed(1)} mm`);
        if (yMm < requiredMm) shortAxes.push(`Y 当前 ${yMm.toFixed(1)} mm，还差 ${(requiredMm - yMm).toFixed(1)} mm`);
        elements.instruction.textContent = `${shortAxes.join('；')}。把标定板继续平放，移到尚未采过的横向或纵向远端，整板清晰可见后补采一次。`;
        elements.primaryButton.textContent = '补采桌面位置';
      } else {
        elements.instruction.textContent = config.instruction;
        elements.primaryButton.textContent = config.button;
      }
      elements.progressText.textContent = `${current} / ${required}`;
      const cells = [];
      for (let index = 0; index < required; index += 1) {
        const cell = createProgressCell();
        cell.textContent = String(index + 1);
        cell.className = index < current ? 'done' : 'pending';
        cells.push(cell);
      }
      elements.progressGrid.replaceChildren(...cells);
      const sample = report.sample;
      elements.sampleId.textContent = sample?.id || '—';
      elements.sampleSplit.textContent = sample?.split === 'validation'
        ? '留出验证' : sample?.split === 'fit' ? '拟合' : '—';
      elements.samplePoints.textContent = Number.isInteger(sample?.detected_points)
        ? String(sample.detected_points) : '—';
      elements.sampleRmse.textContent = metric(sample?.reprojection_rmse_px, 1, 3, ' px');
      elements.relativeStatus.textContent = report.metrics?.relative?.validated === true
        ? '已通过独立验证' : '未通过';
      const handeye = report.metrics?.handeye;
      elements.handeyeMetrics.textContent = handeye
        ? `P95 ${metric(handeye.position_p95_m, 1000, 2, ' mm')} · 图像 ${metric(handeye.reprojection_rmse_px, 1, 3, ' px')}`
        : '待采集 / 待求解';
      const table = report.metrics?.table;
      elements.tableMetrics.textContent = table
        ? `留出 P95 ${metric(table.validation_p95_m, 1000, 2, ' mm')} · 拟合 ${metric(table.fit_rmse_m, 1000, 2, ' mm')}`
        : coverage
          ? `覆盖 X ${metric(coverage.x_span_m, 1000, 1, ' mm')} / ${metric(coverage.required_span_m, 1000, 1, ' mm')} · Y ${metric(coverage.y_span_m, 1000, 1, ' mm')} / ${metric(coverage.required_span_m, 1000, 1, ' mm')}`
          : '待采集 / 待验证';
      elements.blockers.textContent = blockerText(report.remaining_blockers);
      elements.result.className = 'result';
      elements.result.textContent = phase === 'foundation_validated'
        ? '几何基础已通过运行时往返校验；页面没有开启任何运动或抓取权限。'
        : current === 0 ? config.instruction : `当前阶段已完成 ${current} / ${required}。`;
      buttonState();
      return report;
    }

    function showError(error) {
      const instructions = {
        pose_not_distinct: '这个姿态与已采样姿态太接近，请明显移动或倾斜后再采集。',
        target_not_visible: '标定板识别失败：请保证整板清晰、无反光，并在 D435 画面内。',
        robot_state_unstable: '机械臂尚未完全停稳；等待速度归零后再采集。',
        camera_unavailable: 'D435 暂不可用，请先确认左侧画面持续刷新。',
        handeye_solve_failed: '手眼验证未通过：需要补充平移和旋转变化更明显的姿态。',
        table_solve_failed: '桌面验证未通过：请确保板完全平放且 X/Y 覆盖足够。',
        table_coverage_insufficient: '桌面 X/Y 覆盖不足：请按上方的毫米差值把板移到未采过的远端后补采。',
        operation_in_progress: '上一项操作仍在处理，请稍候。',
        source_changed: '标定来源发生变化，已停止。请保留现场并检查文件。',
      };
      elements.result.className = 'result error';
      elements.result.textContent = instructions[error?.code] || '操作失败，请按当前阶段提示检查后重试。';
    }

    async function refresh() {
      if (destroyed || busy || polling || !isVisible()) return null;
      polling = true;
      try { return render(await fetchJson('/api/calibration-completion/status')); }
      catch (error) { showError(error); return null; }
      finally { polling = false; }
    }

    async function runPrimaryAction() {
      const config = PHASES[phase];
      if (destroyed || busy || !config.endpoint) return { accepted: false, reason: 'unavailable' };
      busy = true;
      elements.result.className = 'result working';
      elements.result.textContent = config.working;
      buttonState();
      try {
        const report = await fetchJson(config.endpoint, { method: 'POST' });
        render(report);
        return { accepted: true, report };
      } catch (error) {
        showError(error);
        return { accepted: false, reason: error?.code || 'request_failed' };
      } finally { busy = false; buttonState(); }
    }

    async function poll() {
      await refresh();
      if (!destroyed) timer = schedule(poll, 1800);
    }
    function start() { if (!destroyed && timer === null) poll(); }
    function destroy() { destroyed = true; if (timer !== null) cancelSchedule(timer); timer = null; }
    return Object.freeze({ destroy, refresh, render, runPrimaryAction, start });
  }

  async function browserFetchJson(url, options = {}) {
    const response = await root.fetch(url, {
      ...options,
      headers: { accept: 'application/json' },
      cache: 'no-store',
    });
    let payload;
    try { payload = await response.json(); }
    catch { const error = new Error('invalid JSON'); error.code = 'worker_protocol_invalid'; throw error; }
    if (!response.ok || payload?.ok !== true) {
      const error = new Error(payload?.error?.message || `HTTP ${response.status}`);
      error.code = payload?.error?.code || 'request_failed';
      throw error;
    }
    return payload;
  }

  function preview(image) {
    const source = image?.dataset?.preview;
    if (!source) throw new TypeError('preview source is required');
    let stopped = false;
    let timer = null;
    const load = () => { if (!stopped) image.src = `${source}?frame=${Date.now()}`; };
    image.addEventListener('load', () => { timer = root.setTimeout(load, 450); });
    image.addEventListener('error', () => { timer = root.setTimeout(load, 1200); });
    load();
    return () => { stopped = true; if (timer !== null) root.clearTimeout(timer); };
  }

  function boot(document) {
    const byId = id => document.getElementById(id);
    const client = createCalibrationCompletionClient({
      elements: {
        primaryButton: byId('primary-button'), result: byId('result'), phase: byId('phase'),
        instruction: byId('instruction'), progressText: byId('progress-text'),
        progressGrid: byId('progress-grid'), sampleId: byId('sample-id'),
        sampleSplit: byId('sample-split'), samplePoints: byId('sample-points'),
        sampleRmse: byId('sample-rmse'), relativeStatus: byId('relative-status'),
        handeyeMetrics: byId('handeye-metrics'), tableMetrics: byId('table-metrics'),
        blockers: byId('blockers'),
      },
      fetchJson: browserFetchJson,
      createProgressCell: () => document.createElement('span'),
      schedule: root.setTimeout.bind(root), cancelSchedule: root.clearTimeout.bind(root),
      isVisible: () => document.visibilityState !== 'hidden',
    });
    byId('primary-button').addEventListener('click', () => client.runPrimaryAction());
    preview(byId('d435-preview'));
    client.start();
    return client;
  }

  if (root?.document) root.addEventListener('DOMContentLoaded', () => boot(root.document));
  return Object.freeze({ boot, createCalibrationCompletionClient });
}));
