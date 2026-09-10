'use strict';

(function exposeCalibrationCapture(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandCalibrationCapture = api;
}(typeof globalThis === 'object' ? globalThis : this, function buildCalibrationCapture(root) {
  const ERROR_INSTRUCTIONS = Object.freeze({
    pose_not_distinct: '这个姿态与已采样姿态太接近：请移动至少 15 mm 或倾斜至少 3° 后重试。',
    target_not_visible: '两台相机没有同时完整识别标定板，请把整块板放进两路画面并避免反光。',
    insufficient_common_points: '两台相机共同看到的角点不足，请把标定板移到两路视野重叠区域。',
    d435_pixel_gate_failed: 'D435 重投影误差超限，请保持标定板清晰、稳定并减少反光。',
    validation_pixel_gate_failed: '新外参在这个独立姿态上的误差超限，本次不会计入验证。',
    capture_skew_failed: '两台相机抓帧时差过大，请确认两路画面连续更新后重试。',
    camera_unavailable: '至少一台相机暂时不可用，请先检查两路画面是否都在更新。',
    fit_not_ready: '必须先完成 12 个合格拟合姿态。',
    solve_failed: '求解结果未通过质量门禁；拟合数据已保留，可以重新求解。',
    operation_in_progress: '上一轮采集或求解仍在进行，请等待结果。',
    action_not_available: '页面阶段已变化，正在刷新当前状态。',
    local_access_required: '标定接口只允许从这台 Ubuntu 电脑本机访问。',
  });
  const REQUIRED_ELEMENT_KEYS = [
    'captureButton',
    'result',
    'phaseLabel',
    'progressPurpose',
    'progressText',
    'progressGrid',
    'sampleId',
    'commonPoints',
    'd435Rmse',
    'lumosP95',
    'captureSkew',
    'fitMedian',
    'fitP95',
    'fitBaseline',
    'fitRotation',
    'validation',
    'blockers',
  ];
  const PHASE_CONFIG = Object.freeze({
    fit_collect: {
      label: '阶段 1 / 3 · 采集拟合姿态',
      button: '采集拟合姿态',
      endpoint: '/api/calibration/capture-fit',
      working: '正在同时抓取 Lumos 与 D435 原始帧，并检查拟合姿态质量…',
    },
    fit_ready: {
      label: '阶段 2 / 3 · 求解新外参',
      button: '求解新外参',
      endpoint: '/api/calibration/solve',
      working: '正在固定两台相机内参，鲁棒求解 6 自由度相对外参…',
    },
    validation_collect: {
      label: '阶段 3 / 3 · 独立验证',
      button: '采集验证姿态',
      endpoint: '/api/calibration/capture',
      working: '正在采集未参与拟合的新姿态，并验证新外参像素误差…',
    },
    relative_validated: {
      label: '完成 · 双相机外参通过独立验证',
      button: '相对外参验证完成',
      endpoint: null,
      working: '',
    },
  });

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function requireElements(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      throw new TypeError('elements must be an object');
    }
    for (const key of REQUIRED_ELEMENT_KEYS) {
      if (!value[key] || typeof value[key] !== 'object') {
        throw new TypeError(`elements.${key} is required`);
      }
    }
    if (typeof value.progressGrid.replaceChildren !== 'function') {
      throw new TypeError('progressGrid.replaceChildren must be a function');
    }
    return value;
  }

  function finite(value, digits, suffix) {
    return typeof value === 'number' && Number.isFinite(value)
      ? `${value.toFixed(digits)}${suffix}`
      : '—';
  }

  function blockerText(blockers) {
    const labels = {
      relative_extrinsic_refit_missing: '双相机新外参尚未完成',
      pose_diversity_insufficient: '验证姿态数量不足',
      relative_extrinsic_validation_failed: '双相机外参尚未通过独立验证',
      handeye_validation_missing: '手眼标定待验证',
      table_validation_missing: '桌面标定待验证',
    };
    return Array.isArray(blockers) && blockers.length > 0
      ? blockers.map(item => labels[item] || item).join(' · ')
      : '无';
  }

  function createCalibrationCaptureClient(options = {}) {
    const elements = requireElements(options.elements);
    const fetchJson = requireFunction(options.fetchJson, 'fetchJson');
    const createProgressCell = requireFunction(options.createProgressCell, 'createProgressCell');
    const schedule = requireFunction(options.schedule, 'schedule');
    const cancelSchedule = requireFunction(options.cancelSchedule, 'cancelSchedule');
    const isVisible = requireFunction(options.isVisible, 'isVisible');
    let destroyed = false;
    let busy = false;
    let phase = 'fit_collect';
    let pollInFlight = false;
    let timer = null;

    function setButtonState() {
      elements.captureButton.disabled = destroyed || busy || phase === 'relative_validated';
    }

    function renderSample(sample) {
      elements.sampleId.textContent = sample?.id || '—';
      elements.commonPoints.textContent = Number.isInteger(sample?.common_points)
        ? String(sample.common_points) : '—';
      elements.d435Rmse.textContent = finite(sample?.d435_reprojection_rmse_px, 3, ' px');
      const p95 = finite(sample?.lumos_reprojection_p95_px, 3, ' px');
      elements.lumosP95.textContent = sample?.purpose === 'fit' && p95 !== '—'
        ? `${p95}（旧外参诊断）` : p95;
      elements.captureSkew.textContent = finite(sample?.capture_skew_ms, 1, ' ms');
    }

    function renderFitMetrics(metrics) {
      elements.fitMedian.textContent = finite(metrics?.median_px, 3, ' px');
      elements.fitP95.textContent = finite(metrics?.p95_px, 3, ' px');
      elements.fitBaseline.textContent = typeof metrics?.baseline_m === 'number'
        ? finite(metrics.baseline_m * 1000, 1, ' mm') : '—';
      elements.fitRotation.textContent = finite(metrics?.rotation_deg, 2, '°');
    }

    function render(report) {
      if (!report || report.ok !== true || !PHASE_CONFIG[report.phase] || !report.progress) {
        throw new TypeError('calibration report is invalid');
      }
      const current = Number(report.progress.current);
      const required = Number(report.progress.required);
      if (
        !Number.isInteger(current)
        || !Number.isInteger(required)
        || required <= 0
        || current < 0
        || current > required
      ) {
        throw new TypeError('calibration progress is invalid');
      }
      phase = report.phase;
      const config = PHASE_CONFIG[phase];
      elements.phaseLabel.textContent = config.label;
      elements.captureButton.textContent = config.button;
      elements.progressPurpose.textContent = report.progress.purpose === 'fit'
        ? '拟合集（用于求解）' : '验证集（不参与求解）';
      elements.progressText.textContent = `${current} / ${required}`;
      const cells = [];
      for (let index = 0; index < required; index += 1) {
        const cell = createProgressCell();
        cell.textContent = String(index + 1);
        cell.className = index < current ? 'done' : 'pending';
        cells.push(cell);
      }
      elements.progressGrid.replaceChildren(...cells);
      renderSample(report.sample);
      renderFitMetrics(report.fit_metrics);
      elements.blockers.textContent = blockerText(report.remaining_blockers);

      if (phase === 'fit_collect') {
        elements.validation.textContent = '正在采集拟合数据，旧外参仅作诊断';
        elements.validation.className = 'pending-text';
        elements.result.textContent = current === 0
          ? '把标定板放进两台相机共同视野，稳定后采集第 1 个拟合姿态。'
          : `已有 ${current} 个合格拟合姿态；请明显移动或倾斜标定板后继续。`;
      } else if (phase === 'fit_ready') {
        elements.validation.textContent = '拟合数据齐备，尚未生成新外参';
        elements.validation.className = 'pending-text';
        elements.result.textContent = '12 个拟合姿态已齐备。点击求解；不会移动机械臂。';
      } else if (phase === 'validation_collect') {
        elements.validation.textContent = '新外参已生成，正在收集独立验证';
        elements.validation.className = 'pending-text';
        elements.result.textContent = current === 0
          ? '请换成未参与拟合的新姿态，开始 10 组独立验证。'
          : `已有 ${current} 个验证姿态通过；请换一个新姿态继续。`;
      } else {
        elements.validation.textContent = '双相机外参独立验证通过';
        elements.validation.className = 'ok';
        elements.result.textContent = '相对外参已通过，但手眼与桌面标定仍未完成，不能执行抓取。';
      }
      elements.result.className = '';
      setButtonState();
      return report;
    }

    function showError(error) {
      const code = typeof error?.code === 'string' ? error.code : 'unknown';
      elements.result.textContent = ERROR_INSTRUCTIONS[code]
        || '标定请求失败，请确认两路相机画面正常后重试。';
      elements.result.className = 'error';
    }

    async function refresh() {
      if (destroyed || busy || pollInFlight || !isVisible()) return null;
      pollInFlight = true;
      try {
        const report = await fetchJson('/api/calibration/status');
        return render(report);
      } catch (error) {
        showError(error);
        return null;
      } finally {
        pollInFlight = false;
      }
    }

    async function runPrimaryAction() {
      const config = PHASE_CONFIG[phase];
      if (destroyed || busy || !config.endpoint) {
        return { accepted: false, reason: 'action_unavailable' };
      }
      busy = true;
      elements.result.className = 'working';
      elements.result.textContent = config.working;
      setButtonState();
      try {
        const report = await fetchJson(config.endpoint, { method: 'POST' });
        render(report);
        return { accepted: true, report };
      } catch (error) {
        showError(error);
        return { accepted: false, reason: error?.code || 'request_failed' };
      } finally {
        busy = false;
        setButtonState();
      }
    }

    async function poll() {
      await refresh();
      if (!destroyed) timer = schedule(poll, 1500);
    }

    function start() {
      if (destroyed || timer !== null) return;
      poll();
    }

    function destroy() {
      destroyed = true;
      if (timer !== null) cancelSchedule(timer);
      timer = null;
      setButtonState();
    }

    return Object.freeze({ destroy, refresh, render, runPrimaryAction, start });
  }

  async function browserFetchJson(url, options = {}) {
    const response = await root.fetch(url, {
      ...options,
      headers: { accept: 'application/json' },
      cache: 'no-store',
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      const error = new Error('invalid JSON response');
      error.code = 'worker_protocol_invalid';
      throw error;
    }
    if (!response.ok || payload?.ok !== true) {
      const error = new Error(payload?.error?.message || `HTTP ${response.status}`);
      error.code = payload?.error?.code || 'request_failed';
      throw error;
    }
    return payload;
  }

  function startSnapshotPreview(image) {
    const source = image?.dataset?.preview;
    if (typeof source !== 'string' || source.length === 0) {
      throw new TypeError('preview image requires data-preview');
    }
    let stopped = false;
    let timer = null;
    const scheduleNext = delay => {
      if (stopped) return;
      timer = root.setTimeout(refresh, delay);
    };
    const refresh = () => {
      if (stopped) return;
      const separator = source.includes('?') ? '&' : '?';
      image.src = `${source}${separator}frame=${Date.now()}`;
    };
    image.addEventListener('load', () => scheduleNext(400));
    image.addEventListener('error', () => scheduleNext(1200));
    refresh();
    return () => {
      stopped = true;
      if (timer !== null) root.clearTimeout(timer);
      timer = null;
      image.removeAttribute('src');
    };
  }

  function boot(document) {
    const byId = id => document.getElementById(id);
    const elements = {
      captureButton: byId('capture-button'),
      result: byId('capture-result'),
      phaseLabel: byId('phase-label'),
      progressPurpose: byId('progress-purpose'),
      progressText: byId('progress-text'),
      progressGrid: byId('progress-grid'),
      sampleId: byId('sample-id'),
      commonPoints: byId('common-points'),
      d435Rmse: byId('d435-rmse'),
      lumosP95: byId('lumos-p95'),
      captureSkew: byId('capture-skew'),
      fitMedian: byId('fit-median'),
      fitP95: byId('fit-p95'),
      fitBaseline: byId('fit-baseline'),
      fitRotation: byId('fit-rotation'),
      validation: byId('validation-state'),
      blockers: byId('remaining-blockers'),
    };
    const stopPreviews = [...document.querySelectorAll('img[data-preview]')]
      .map(startSnapshotPreview);
    const client = createCalibrationCaptureClient({
      elements,
      fetchJson: browserFetchJson,
      createProgressCell: () => document.createElement('span'),
      schedule: root.setTimeout.bind(root),
      cancelSchedule: root.clearTimeout.bind(root),
      isVisible: () => !document.hidden,
    });
    elements.captureButton.addEventListener('click', () => client.runPrimaryAction());
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) client.refresh();
    });
    root.addEventListener('beforeunload', () => {
      for (const stopPreview of stopPreviews) stopPreview();
      client.destroy();
    }, { once: true });
    client.start();
    return client;
  }

  if (root?.document) {
    root.document.addEventListener('DOMContentLoaded', () => boot(root.document), { once: true });
  }

  return Object.freeze({ createCalibrationCaptureClient, boot, startSnapshotPreview });
}));
