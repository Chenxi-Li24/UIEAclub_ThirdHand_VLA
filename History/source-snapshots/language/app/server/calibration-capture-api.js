'use strict';

const express = require('express');
const path = require('path');
const { spawn } = require('child_process');

const MAX_OUTPUT_BYTES = 1024 * 1024;
const CAPTURE_TIMEOUT_MS = 15000;
const SOLVE_TIMEOUT_MS = 60000;
const ERROR_MESSAGES = Object.freeze({
  target_not_visible: '标定板未同时被两台相机识别',
  pose_not_distinct: '请明显移动或倾斜标定板后重试',
  insufficient_common_points: '两台相机共同识别的角点不足',
  d435_pixel_gate_failed: 'D435 标定板重投影误差超限',
  capture_skew_failed: '两台相机抓帧时差超过 100 ms',
  camera_unavailable: '至少一台相机当前不可用',
  fit_not_ready: '必须先采满 12 个合格拟合姿态',
  solve_failed: '新外参求解未通过质量门禁',
  candidate_not_ready: '新外参尚未生成',
  validation_pixel_gate_failed: '独立验证像素误差超限',
  capture_rejected: '本次标定操作被安全门禁拒绝',
  operation_in_progress: '上一次采集或求解尚未完成',
  action_not_available: '当前阶段不允许此操作',
  local_access_required: '仅允许本机访问标定采集接口',
  same_origin_required: '浏览器请求必须来自当前标定页面',
  worker_timeout: '标定处理超时',
  worker_protocol_invalid: '标定进程返回了无效响应',
  service_unavailable: '标定采集服务当前不可用',
});
const PUBLIC_WORKER_CODES = new Set([
  'target_not_visible',
  'pose_not_distinct',
  'insufficient_common_points',
  'd435_pixel_gate_failed',
  'capture_skew_failed',
  'camera_unavailable',
  'fit_not_ready',
  'solve_failed',
  'candidate_not_ready',
  'validation_pixel_gate_failed',
  'capture_rejected',
]);
const PHASES = new Set([
  'fit_collect',
  'fit_ready',
  'validation_collect',
  'relative_validated',
]);

class CalibrationCaptureApiError extends Error {
  constructor(code, status) {
    super(ERROR_MESSAGES[code] || ERROR_MESSAGES.service_unavailable);
    this.name = 'CalibrationCaptureApiError';
    this.code = ERROR_MESSAGES[code] ? code : 'service_unavailable';
    this.status = status;
  }
}

function requireString(value, name) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 4096) {
    throw new TypeError(`${name} must be a bounded non-empty string`);
  }
  return value;
}

function requireAbsolutePath(value, name) {
  const normalized = requireString(value, name);
  if (!path.isAbsolute(normalized)) throw new TypeError(`${name} must be absolute`);
  return normalized;
}

function requireLoopbackUrl(value, name) {
  const normalized = requireString(value, name);
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new TypeError(`${name} must be a URL`);
  }
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)) {
    throw new TypeError(`${name} must be a loopback HTTP URL`);
  }
  return normalized;
}

function safeInteger(value, name, maximum = 100000) {
  if (!Number.isInteger(value) || value < 0 || value > maximum) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return value;
}

function safeFinite(value) {
  if (value === null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return value;
}

function sanitizeProgress(progress) {
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  const current = safeInteger(progress.current, 'current', 64);
  const required = safeInteger(progress.required, 'required', 64);
  if (required === 0 || current > required || !['fit', 'validation'].includes(progress.purpose)) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return { current, required, purpose: progress.purpose };
}

function sanitizeSample(sample) {
  if (sample === null) return null;
  if (!sample || typeof sample !== 'object' || Array.isArray(sample)) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  const purpose = sample.purpose;
  const pattern = purpose === 'fit' ? /^fit-[0-9]{2}$/ : /^pose-[0-9]{2}$/;
  if (!['fit', 'validation'].includes(purpose) || typeof sample.id !== 'string' || !pattern.test(sample.id)) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  if (typeof sample.passes_pixel_gate !== 'boolean') {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return {
    id: sample.id,
    purpose,
    common_points: safeInteger(sample.common_points, 'common_points', 10000),
    d435_reprojection_rmse_px: safeFinite(sample.d435_reprojection_rmse_px),
    lumos_reprojection_median_px: safeFinite(sample.lumos_reprojection_median_px),
    lumos_reprojection_p95_px: safeFinite(sample.lumos_reprojection_p95_px),
    capture_skew_ms: safeFinite(sample.capture_skew_ms),
    passes_pixel_gate: sample.passes_pixel_gate,
  };
}

function sanitizeFitMetrics(metrics) {
  if (metrics === null) return null;
  if (!metrics || typeof metrics !== 'object' || Array.isArray(metrics)) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return {
    samples: safeInteger(metrics.samples, 'samples', 64),
    corners: safeInteger(metrics.corners, 'corners'),
    median_px: safeFinite(metrics.median_px),
    p95_px: safeFinite(metrics.p95_px),
    baseline_m: safeFinite(metrics.baseline_m),
    rotation_deg: safeFinite(metrics.rotation_deg),
    nfev: safeInteger(metrics.nfev, 'nfev'),
  };
}

function parseWorkerReport(stdout, expectedAction) {
  let payload;
  try {
    payload = JSON.parse(stdout.trim());
  } catch {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  if (!payload || typeof payload !== 'object' || payload.schema_version !== 1) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  if (payload.ok === false) {
    const code = payload.error?.code;
    if (!PUBLIC_WORKER_CODES.has(code)) {
      throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
    }
    throw new CalibrationCaptureApiError(code, 422);
  }
  if (
    payload.ok !== true
    || payload.action !== expectedAction
    || !PHASES.has(payload.phase)
    || typeof payload.relative_extrinsic_validated !== 'boolean'
    || payload.safety?.motion_or_robot_access !== false
    || payload.safety?.executable !== false
  ) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  const blockers = payload.remaining_blockers;
  if (!Array.isArray(blockers) || blockers.length > 16 || blockers.some(
    item => typeof item !== 'string' || item.length === 0 || item.length > 96
  )) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  const progress = sanitizeProgress(payload.progress);
  const phasePurpose = payload.phase.startsWith('fit_') ? 'fit' : 'validation';
  if (progress.purpose !== phasePurpose) {
    throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
  }
  return {
    schema_version: 1,
    ok: true,
    action: expectedAction,
    phase: payload.phase,
    progress,
    sample: sanitizeSample(payload.sample),
    fit_metrics: sanitizeFitMetrics(payload.fit_metrics),
    relative_extrinsic_validated: payload.relative_extrinsic_validated,
    remaining_blockers: [...blockers],
    safety: { motion_or_robot_access: false, executable: false },
  };
}

function defaultRunProgram({ command, args, cwd, timeoutMs, maxOutputBytes }) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const stdout = [];
    const stderr = [];
    let bytes = 0;
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill('SIGKILL');
      reject(new CalibrationCaptureApiError('worker_timeout', 504));
    }, timeoutMs);
    function collect(destination, chunk) {
      if (settled) return;
      bytes += chunk.length;
      if (bytes > maxOutputBytes) {
        settled = true;
        clearTimeout(timer);
        child.kill('SIGKILL');
        reject(new CalibrationCaptureApiError('worker_protocol_invalid', 502));
        return;
      }
      destination.push(chunk);
    }
    child.stdout.on('data', chunk => collect(stdout, chunk));
    child.stderr.on('data', chunk => collect(stderr, chunk));
    child.once('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new CalibrationCaptureApiError('service_unavailable', 503));
    });
    child.once('close', code => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        code: Number.isInteger(code) ? code : 1,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
      });
    });
  });
}

class CalibrationCaptureService {
  constructor(options = {}) {
    this.python = requireAbsolutePath(options.python, 'python');
    this.script = requireAbsolutePath(options.script, 'script');
    this.fitOutput = requireAbsolutePath(options.fitOutput, 'fitOutput');
    this.validationOutput = requireAbsolutePath(options.validationOutput, 'validationOutput');
    this.candidateOutput = requireAbsolutePath(options.candidateOutput, 'candidateOutput');
    this.seed = requireAbsolutePath(options.seed, 'seed');
    this.target = requireAbsolutePath(options.target, 'target');
    this.lumosUrl = requireLoopbackUrl(options.lumosUrl, 'lumosUrl');
    this.d435Url = requireLoopbackUrl(options.d435Url, 'd435Url');
    this.cwd = options.cwd === undefined
      ? path.resolve(__dirname, '../..')
      : requireAbsolutePath(options.cwd, 'cwd');
    this.runProgram = options.runProgram || defaultRunProgram;
    if (typeof this.runProgram !== 'function') throw new TypeError('runProgram must be a function');
    this.operationInProgress = false;
  }

  _args(action) {
    return [
      this.script,
      '--action', action,
      '--fit-output', this.fitOutput,
      '--validation-output', this.validationOutput,
      '--candidate-output', this.candidateOutput,
      '--seed', this.seed,
      '--target', this.target,
      '--lumos-url', this.lumosUrl,
      '--d435-url', this.d435Url,
      '--json',
    ];
  }

  async _invoke(cliAction, expectedAction, timeoutMs) {
    let result;
    try {
      result = await this.runProgram({
        command: this.python,
        args: this._args(cliAction),
        cwd: this.cwd,
        timeoutMs,
        maxOutputBytes: MAX_OUTPUT_BYTES,
      });
    } catch (error) {
      if (error instanceof CalibrationCaptureApiError) throw error;
      throw new CalibrationCaptureApiError('service_unavailable', 503);
    }
    if (
      !result || typeof result !== 'object'
      || typeof result.stdout !== 'string'
      || typeof result.stderr !== 'string'
      || !Number.isInteger(result.code)
      || Buffer.byteLength(result.stdout) + Buffer.byteLength(result.stderr) > MAX_OUTPUT_BYTES
    ) {
      throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
    }
    const report = parseWorkerReport(result.stdout, expectedAction);
    if (result.code !== 0) {
      throw new CalibrationCaptureApiError('worker_protocol_invalid', 502);
    }
    return report;
  }

  status() {
    return this._invoke('status', 'status', CAPTURE_TIMEOUT_MS);
  }

  async _operate(requiredPhase, cliAction, expectedAction, timeoutMs) {
    if (this.operationInProgress) {
      throw new CalibrationCaptureApiError('operation_in_progress', 409);
    }
    this.operationInProgress = true;
    try {
      const current = await this.status();
      if (current.phase !== requiredPhase) {
        throw new CalibrationCaptureApiError('action_not_available', 409);
      }
      return await this._invoke(cliAction, expectedAction, timeoutMs);
    } finally {
      this.operationInProgress = false;
    }
  }

  captureFit() {
    return this._operate('fit_collect', 'capture-fit', 'capture_fit', CAPTURE_TIMEOUT_MS);
  }

  solve() {
    return this._operate('fit_ready', 'solve', 'solve', SOLVE_TIMEOUT_MS);
  }

  captureValidation() {
    return this._operate(
      'validation_collect',
      'capture-validation',
      'capture_validation',
      CAPTURE_TIMEOUT_MS
    );
  }
}

function requestIsLoopback(request) {
  const address = request.socket?.remoteAddress;
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1';
}

function requestHasSameOrigin(request) {
  const origin = request.headers?.origin;
  if (origin === undefined) return true;
  if (typeof origin !== 'string' || typeof request.headers?.host !== 'string') return false;
  try {
    const parsed = new URL(origin);
    return ['http:', 'https:'].includes(parsed.protocol) && parsed.host === request.headers.host;
  } catch {
    return false;
  }
}

function publicError(error) {
  const safe = error instanceof CalibrationCaptureApiError
    ? error
    : new CalibrationCaptureApiError('service_unavailable', 503);
  return {
    status: safe.status,
    body: {
      schema_version: 1,
      ok: false,
      error: { code: safe.code, message: ERROR_MESSAGES[safe.code] },
    },
  };
}

function createCalibrationCaptureRouter({ service, isLoopback = requestIsLoopback } = {}) {
  if (!(service instanceof CalibrationCaptureService)) {
    throw new TypeError('service must be a CalibrationCaptureService');
  }
  if (typeof isLoopback !== 'function') throw new TypeError('isLoopback must be a function');
  const router = express.Router();
  router.use((request, response, next) => {
    response.setHeader('Cache-Control', 'no-store');
    if (!isLoopback(request)) {
      const denied = publicError(new CalibrationCaptureApiError('local_access_required', 403));
      response.status(denied.status).json(denied.body);
      return;
    }
    if (!requestHasSameOrigin(request)) {
      const denied = publicError(new CalibrationCaptureApiError('same_origin_required', 403));
      response.status(denied.status).json(denied.body);
      return;
    }
    next();
  });
  async function send(response, operation) {
    try {
      response.json(await operation());
    } catch (error) {
      const rejected = publicError(error);
      response.status(rejected.status).json(rejected.body);
    }
  }
  router.get('/status', (_request, response) => send(response, () => service.status()));
  router.post('/capture-fit', (_request, response) => send(response, () => service.captureFit()));
  router.post('/solve', (_request, response) => send(response, () => service.solve()));
  router.post('/capture', (_request, response) => send(
    response,
    () => service.captureValidation()
  ));
  return router;
}

module.exports = {
  CalibrationCaptureApiError,
  CalibrationCaptureService,
  createCalibrationCaptureRouter,
  defaultRunProgram,
};
