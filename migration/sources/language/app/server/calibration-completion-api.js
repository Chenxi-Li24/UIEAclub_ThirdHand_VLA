'use strict';

const express = require('express');
const path = require('path');
const { spawn } = require('child_process');

const MAX_OUTPUT_BYTES = 1024 * 1024;
const CAPTURE_TIMEOUT_MS = 20000;
const SOLVE_TIMEOUT_MS = 90000;
const PHASES = new Set([
  'handeye_collect',
  'handeye_solve',
  'table_collect',
  'finalize',
  'foundation_validated',
]);
const PUBLIC_CODES = new Set([
  'pose_not_distinct',
  'target_not_visible',
  'robot_state_unstable',
  'camera_unavailable',
  'handeye_not_ready',
  'handeye_solve_failed',
  'table_not_ready',
  'table_solve_failed',
  'table_coverage_insufficient',
  'source_changed',
  'action_not_available',
  'capture_rejected',
]);
const MESSAGES = Object.freeze({
  pose_not_distinct: '当前姿态与已采样姿态太接近，请明显移动或倾斜后重试',
  target_not_visible: 'D435 未稳定识别标定板，请调整标定板后重试',
  robot_state_unstable: '机械臂仍在运动或状态不稳定，请停止后重试',
  camera_unavailable: 'D435 当前不可用，请确认画面正常',
  handeye_not_ready: '手眼标定必须先采满 15 个合格姿态',
  handeye_solve_failed: '手眼求解未通过独立验证，请补充更分散的姿态',
  table_not_ready: '桌面标定必须先采满 8 个合格位置',
  table_solve_failed: '桌面平面未通过留出验证，请重新摆放标定板采集',
  table_coverage_insufficient: '桌面 X/Y 覆盖不足，请按页面提示补采更远位置',
  source_changed: '标定来源或文件完整性发生变化，已停止',
  action_not_available: '当前阶段不允许这个操作',
  capture_rejected: '本次标定操作被质量门禁拒绝',
  operation_in_progress: '上一项标定操作尚未完成',
  local_access_required: '仅允许从这台 Ubuntu 电脑本机访问',
  same_origin_required: '浏览器请求必须来自当前标定页面',
  worker_timeout: '标定处理超时',
  worker_protocol_invalid: '标定进程返回了无效响应',
  service_unavailable: '标定完成服务当前不可用',
});

class CalibrationCompletionApiError extends Error {
  constructor(code, status) {
    const safeCode = Object.hasOwn(MESSAGES, code) ? code : 'service_unavailable';
    super(MESSAGES[safeCode]);
    this.code = safeCode;
    this.status = status;
  }
}

function requireString(value, name) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 4096) {
    throw new TypeError(`${name} must be a bounded non-empty string`);
  }
  return value;
}

function absolutePath(value, name) {
  const normalized = requireString(value, name);
  if (!path.isAbsolute(normalized)) throw new TypeError(`${name} must be absolute`);
  return normalized;
}

function loopbackUrl(value, name, protocols) {
  const normalized = requireString(value, name);
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new TypeError(`${name} must be a URL`);
  }
  if (
    !protocols.includes(parsed.protocol)
    || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || parsed.username
    || parsed.password
  ) {
    throw new TypeError(`${name} must be a loopback URL`);
  }
  return normalized;
}

function finite(value, name, maximum = 1000) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > maximum) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return value;
}

function integer(value, name, maximum) {
  if (!Number.isInteger(value) || value < 0 || value > maximum) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return value;
}

function contentId(value, nullable = false) {
  if (nullable && value === null) return null;
  if (typeof value !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(value)) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return value;
}

function sample(value) {
  if (value === null) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  if (
    typeof value.id !== 'string'
    || !/^(pose|table)-[0-9]{2}$/.test(value.id)
    || !['fit', 'validation'].includes(value.split)
  ) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return {
    id: value.id,
    split: value.split,
    detected_points: integer(value.detected_points, 'detected_points', 10000),
    reprojection_rmse_px: finite(value.reprojection_rmse_px, 'reprojection_rmse_px', 100),
  };
}

function optionalMetrics(value, kind) {
  if (value === null) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  if (kind === 'handeye') {
    return {
      position_rmse_m: finite(value.position_rmse_m, 'position_rmse_m', 1),
      position_p95_m: finite(value.position_p95_m, 'position_p95_m', 1),
      reprojection_rmse_px: finite(value.reprojection_rmse_px, 'reprojection_rmse_px', 100),
    };
  }
  return {
    fit_rmse_m: finite(value.fit_rmse_m, 'fit_rmse_m', 1),
    validation_p95_m: finite(value.validation_p95_m, 'validation_p95_m', 1),
  };
}

function optionalTableCoverage(value) {
  if (value === null) return null;
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return {
    x_span_m: finite(value.x_span_m, 'x_span_m', 1),
    y_span_m: finite(value.y_span_m, 'y_span_m', 1),
    required_span_m: finite(value.required_span_m, 'required_span_m', 1),
  };
}

function parseReport(stdout, expectedAction) {
  let payload;
  try {
    payload = JSON.parse(stdout.trim());
  } catch {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  if (payload?.ok === false) {
    const code = payload.error?.code;
    if (!PUBLIC_CODES.has(code)) {
      throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
    }
    throw new CalibrationCompletionApiError(code, 422);
  }
  if (
    !payload || payload.schema_version !== 1 || payload.ok !== true
    || payload.action !== expectedAction || !PHASES.has(payload.phase)
    || payload.safety?.robot_state_access !== 'read_only_status'
    || payload.safety?.motion_command_access !== false
    || payload.safety?.executable !== false
    || payload.metrics?.relative?.validated !== true
  ) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  const current = integer(payload.progress?.current, 'current', 15);
  const required = integer(payload.progress?.required, 'required', 15);
  if (required === 0 || current > required) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  const blockers = payload.remaining_blockers;
  if (
    !Array.isArray(blockers) || blockers.length > 12
    || blockers.some(value => typeof value !== 'string' || value.length === 0 || value.length > 96)
  ) {
    throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
  }
  return {
    schema_version: 1,
    ok: true,
    action: expectedAction,
    phase: payload.phase,
    progress: { current, required },
    sample: sample(payload.sample),
    metrics: {
      relative: { validated: true },
      handeye: optionalMetrics(payload.metrics.handeye, 'handeye'),
      table: optionalMetrics(payload.metrics.table, 'table'),
      table_coverage: optionalTableCoverage(payload.metrics.table_coverage),
    },
    remaining_blockers: [...blockers],
    source_ids: {
      candidate: contentId(payload.source_ids?.candidate),
      relative_validation: contentId(payload.source_ids?.relative_validation),
      handeye: contentId(payload.source_ids?.handeye, true),
      table: contentId(payload.source_ids?.table, true),
    },
    safety: {
      robot_state_access: 'read_only_status',
      motion_command_access: false,
      executable: false,
    },
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
      reject(new CalibrationCompletionApiError('worker_timeout', 504));
    }, timeoutMs);
    function collect(target, chunk) {
      if (settled) return;
      bytes += chunk.length;
      if (bytes > maxOutputBytes) {
        settled = true;
        clearTimeout(timer);
        child.kill('SIGKILL');
        reject(new CalibrationCompletionApiError('worker_protocol_invalid', 502));
        return;
      }
      target.push(chunk);
    }
    child.stdout.on('data', chunk => collect(stdout, chunk));
    child.stderr.on('data', chunk => collect(stderr, chunk));
    child.once('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(new CalibrationCompletionApiError('service_unavailable', 503));
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

class CalibrationCompletionService {
  constructor(options = {}) {
    this.python = absolutePath(options.python, 'python');
    this.script = absolutePath(options.script, 'script');
    this.candidate = absolutePath(options.candidate, 'candidate');
    this.relativeValidation = absolutePath(options.relativeValidation, 'relativeValidation');
    this.handeyeOutput = absolutePath(options.handeyeOutput, 'handeyeOutput');
    this.handeyeResult = absolutePath(options.handeyeResult, 'handeyeResult');
    this.tableOutput = absolutePath(options.tableOutput, 'tableOutput');
    this.tableResult = absolutePath(options.tableResult, 'tableResult');
    this.foundationOutput = absolutePath(options.foundationOutput, 'foundationOutput');
    this.target = absolutePath(options.target, 'target');
    this.d435Url = loopbackUrl(options.d435Url, 'd435Url', ['http:']);
    this.robotUrl = loopbackUrl(options.robotUrl, 'robotUrl', ['ws:', 'wss:']);
    this.cwd = options.cwd === undefined
      ? path.resolve(__dirname, '../..')
      : absolutePath(options.cwd, 'cwd');
    this.runProgram = options.runProgram || defaultRunProgram;
    if (typeof this.runProgram !== 'function') throw new TypeError('runProgram must be a function');
    this.operationInProgress = false;
  }

  _args(action) {
    return [
      this.script,
      '--action', action,
      '--candidate', this.candidate,
      '--relative-validation', this.relativeValidation,
      '--handeye-output', this.handeyeOutput,
      '--handeye-result', this.handeyeResult,
      '--table-output', this.tableOutput,
      '--table-result', this.tableResult,
      '--foundation-output', this.foundationOutput,
      '--target', this.target,
      '--d435-url', this.d435Url,
      '--robot-url', this.robotUrl,
      '--json',
    ];
  }

  async _invoke(action, timeoutMs) {
    let result;
    try {
      result = await this.runProgram({
        command: this.python,
        args: this._args(action),
        cwd: this.cwd,
        timeoutMs,
        maxOutputBytes: MAX_OUTPUT_BYTES,
      });
    } catch (error) {
      if (error instanceof CalibrationCompletionApiError) throw error;
      throw new CalibrationCompletionApiError('service_unavailable', 503);
    }
    if (
      !result || typeof result.stdout !== 'string' || typeof result.stderr !== 'string'
      || !Number.isInteger(result.code)
      || Buffer.byteLength(result.stdout) + Buffer.byteLength(result.stderr) > MAX_OUTPUT_BYTES
    ) {
      throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
    }
    const report = parseReport(result.stdout, action.replaceAll('-', '_'));
    if (result.code !== 0) {
      throw new CalibrationCompletionApiError('worker_protocol_invalid', 502);
    }
    return report;
  }

  status() {
    return this._invoke('status', CAPTURE_TIMEOUT_MS);
  }

  async operate(action, requiredPhase, timeoutMs) {
    if (this.operationInProgress) {
      throw new CalibrationCompletionApiError('operation_in_progress', 409);
    }
    this.operationInProgress = true;
    try {
      const current = await this.status();
      if (current.phase !== requiredPhase) {
        throw new CalibrationCompletionApiError('action_not_available', 409);
      }
      return await this._invoke(action, timeoutMs);
    } finally {
      this.operationInProgress = false;
    }
  }

  captureHandeye() {
    return this.operate('capture-handeye', 'handeye_collect', CAPTURE_TIMEOUT_MS);
  }

  solveHandeye() {
    return this.operate('solve-handeye', 'handeye_solve', SOLVE_TIMEOUT_MS);
  }

  captureTable() {
    return this.operate('capture-table', 'table_collect', CAPTURE_TIMEOUT_MS);
  }

  finalize() {
    return this.operate('finalize', 'finalize', SOLVE_TIMEOUT_MS);
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
  const safe = error instanceof CalibrationCompletionApiError
    ? error
    : new CalibrationCompletionApiError('service_unavailable', 503);
  return {
    status: safe.status,
    body: {
      schema_version: 1,
      ok: false,
      error: { code: safe.code, message: MESSAGES[safe.code] },
    },
  };
}

function createCalibrationCompletionRouter({ service, isLoopback = requestIsLoopback } = {}) {
  if (!(service instanceof CalibrationCompletionService)) {
    throw new TypeError('service must be a CalibrationCompletionService');
  }
  if (typeof isLoopback !== 'function') throw new TypeError('isLoopback must be a function');
  const router = express.Router();
  router.use((request, response, next) => {
    response.setHeader('Cache-Control', 'no-store');
    if (!isLoopback(request)) {
      const denied = publicError(new CalibrationCompletionApiError('local_access_required', 403));
      response.status(denied.status).json(denied.body);
      return;
    }
    if (!requestHasSameOrigin(request)) {
      const denied = publicError(new CalibrationCompletionApiError('same_origin_required', 403));
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
  router.post('/capture-handeye', (_request, response) => send(
    response,
    () => service.captureHandeye()
  ));
  router.post('/solve-handeye', (_request, response) => send(
    response,
    () => service.solveHandeye()
  ));
  router.post('/capture-table', (_request, response) => send(
    response,
    () => service.captureTable()
  ));
  router.post('/finalize', (_request, response) => send(response, () => service.finalize()));
  return router;
}

module.exports = {
  CalibrationCompletionApiError,
  CalibrationCompletionService,
  createCalibrationCompletionRouter,
  defaultRunProgram,
};
