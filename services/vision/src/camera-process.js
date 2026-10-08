'use strict';

const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const readline = require('node:readline');

function buildBridgeArgs(config) {
  const args = [
    '-u', config.bridgeScript,
    '--config', config.visionConfig,
    '--executable', config.xvisioExecutable,
  ];
  if (config.handeye) {
    if (!config.robotUrdf) {
      throw new Error('handeye requires THIRDHAND_ROBOT_URDF');
    }
    args.push('--handeye', config.handeye, '--urdf', config.robotUrdf);
  }
  return args;
}

class LatestMjpegBroadcaster {
  constructor({ maxPartBytes = 3 * 1024 * 1024 } = {}) {
    this.maxPartBytes = maxPartBytes;
    this.boundary = Buffer.from('--frame\r\n');
    this.headerEnd = Buffer.from('\r\n\r\n');
    this.buffer = Buffer.alloc(0);
    this.latest = null;
    this.clients = new Map();
  }

  push(chunk) {
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    if (this.buffer.length > this.maxPartBytes * 2) {
      this.buffer = Buffer.alloc(0);
      return;
    }
    while (this.buffer.length) {
      const start = this.buffer.indexOf(this.boundary);
      if (start < 0) {
        this.buffer = this.buffer.subarray(
          Math.max(0, this.buffer.length - this.boundary.length),
        );
        return;
      }
      if (start > 0) this.buffer = this.buffer.subarray(start);
      const headersEnd = this.buffer.indexOf(
        this.headerEnd,
        this.boundary.length,
      );
      if (headersEnd < 0) return;
      const headers = this.buffer
        .subarray(this.boundary.length, headersEnd)
        .toString('ascii');
      const match = headers.match(/(?:^|\r\n)Content-Length:\s*(\d+)/i);
      if (!match) {
        this.buffer = this.buffer.subarray(this.boundary.length);
        continue;
      }
      const length = Number(match[1]);
      if (!Number.isSafeInteger(length) || length < 4 ||
          length > this.maxPartBytes) {
        this.buffer = Buffer.alloc(0);
        return;
      }
      const end = headersEnd + this.headerEnd.length + length + 2;
      if (this.buffer.length < end) return;
      const part = Buffer.from(this.buffer.subarray(0, end));
      this.buffer = this.buffer.subarray(end);
      this.latest = part;
      this._broadcast(part);
    }
  }

  subscribe(response) {
    const state = { blocked: false, pending: null };
    const onDrain = () => {
      state.blocked = false;
      const pending = state.pending;
      state.pending = null;
      if (pending && this.clients.has(response)) {
        this._write(response, state, pending);
      }
    };
    state.onDrain = onDrain;
    response.on('drain', onDrain);
    this.clients.set(response, state);
    if (this.latest) this._write(response, state, this.latest);
    return true;
  }

  subscriberCount() {
    return this.clients.size;
  }

  unsubscribe(response) {
    const state = this.clients.get(response);
    if (!state) return false;
    response.removeListener('drain', state.onDrain);
    this.clients.delete(response);
    return true;
  }

  _broadcast(part) {
    for (const [response, state] of this.clients) {
      if (response.destroyed || response.writableEnded) {
        this.unsubscribe(response);
      } else if (state.blocked) {
        state.pending = part;
      } else {
        this._write(response, state, part);
      }
    }
  }

  _write(response, state, part) {
    try {
      state.blocked = response.write(part) === false;
    } catch {
      this.unsubscribe(response);
    }
  }

  close() {
    for (const [response, state] of this.clients) {
      response.removeListener('drain', state.onDrain);
      if (!response.destroyed) response.end();
    }
    this.clients.clear();
    this.buffer = Buffer.alloc(0);
    this.latest = null;
  }

  reset() {
    this.buffer = Buffer.alloc(0);
    this.latest = null;
    for (const state of this.clients.values()) state.pending = null;
  }
}

class CameraProcess extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.child = null;
    this.meituanReady = false;
    this.closing = false;
    this.restartTimer = null;
    this.restartDelayMs = Number(config.restartDelayMs || 2000);
    this.exportTimeoutMs = Number(config.exportTimeoutMs || 10000);
    this.pendingExport = null;
    this.pendingRawExport = null;
    this._status = {
      camera: { status: 'stopped', sequence: null, error: null },
      inference: { status: 'stopped', error: null },
      selection: { stableId: null },
    };
    this.runtimeEvidence = null;
    this.lastDetection = null;
    this.streams = {
      raw: new LatestMjpegBroadcaster(),
      vision: new LatestMjpegBroadcaster(),
      depth: new LatestMjpegBroadcaster(),
    };
  }

  start() {
    if (this.child) return;
    this.closing = false;
    this.meituanReady = false;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this._status.camera = {
      status: 'starting',
      sequence: null,
      error: null,
    };
    this._status.inference = { status: 'loading', error: null };
    this.runtimeEvidence = null;
    this.lastDetection = null;
    for (const stream of Object.values(this.streams)) stream.reset();
    const child = spawn(
      this.config.python,
      buildBridgeArgs(this.config),
      {
        cwd: this.config.root,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          PYTHONPATH: [
            `${this.config.root}/services/vision/python`,
            process.env.PYTHONPATH,
          ].filter(Boolean).join(require('node:path').delimiter),
          CAMERA_EVENT_FD: '3',
          XVISIO_RAW_FD: '4',
          VISION_OVERLAY_FD: '5',
          DEPTH_HEATMAP_FD: '6',
          SELECTED_TARGET_EXPORT_DIR: this.config.selectedTargetExportDir,
        },
        stdio: ['pipe', 'ignore', 'pipe', 'pipe', 'pipe', 'pipe', 'pipe'],
      },
    );
    this.child = child;
    child.stdio[4].on('data', chunk => this.streams.raw.push(chunk));
    child.stdio[5].on('data', chunk => this.streams.vision.push(chunk));
    child.stdio[6].on('data', chunk => this.streams.depth.push(chunk));
    for (const [kind, stream] of Object.entries(this.streams)) {
      if (stream.subscriberCount() > 0) {
        this._setStreamEnabled(kind, true);
      }
    }
    const events = readline.createInterface({ input: child.stdio[3] });
    events.on('line', line => this._handleEvent(line));
    child.stderr.on('data', chunk => {
      const message = chunk.toString('utf8').trim();
      if (message) this.emit('log', { level: 'warning', message });
    });
    child.on('error', error => {
      if (this.child !== child) return;
      this.child = null;
      this._setProcessError(error);
      this._scheduleRestart();
    });
    child.on('exit', (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      if (!this.closing) {
        this._setProcessError(
          new Error(`camera bridge exited: ${signal || code}`),
        );
        this._scheduleRestart();
      }
    });
  }

  _scheduleRestart() {
    if (this.closing || this.restartTimer) return;
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.closing) this.start();
    }, this.restartDelayMs);
    this.restartTimer.unref();
  }

  _handleEvent(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.emit('log', {
        level: 'warning',
        message: `invalid camera event: ${line}`,
      });
      return;
    }
    if (typeof message.type === 'string' && message.type.startsWith('meituan_')) {
      if (message.type === 'meituan_ready') this.meituanReady = true;
      this.emit('meituan', message);
      return;
    }
    if (message.type === 'runtime_status') {
      this._status = {
        camera: { ...message.camera },
        inference: { ...message.inference },
        selection: { ...message.selection },
      };
    } else if (message.type === 'bridge_ready') {
      this.runtimeEvidence = Object.freeze({
        camera_serial: message.camera_serial,
        registration_id: message.registration_id,
        camera_mount_id: message.camera_mount_id,
        vision_config_id: message.vision_config_id,
        calibration_id: message.calibration_id ?? null,
        calibration_approved: message.calibration_approved === true,
        model_provenance: message.model_provenance || null,
      });
    } else if (message.type === 'detection_result') {
      this.lastDetection = message;
    } else if (message.type === 'selected_target_export_result') {
      this._handleExportResult(message);
    } else if (message.type === 'raw_frame_export_result') {
      this._handleRawExportResult(message);
    }
    this.emit('event', message);
  }

  _removeExport(pathname) {
    if (!pathname) return;
    fs.promises.unlink(pathname).catch(error => {
      if (error.code !== 'ENOENT') {
        this.emit('log', { level: 'warning', message: error.message });
      }
    });
  }

  _handleExportResult(message) {
    const pending = this.pendingExport;
    if (!pending || pending.requestId !== message.requestId) {
      this._removeExport(message.path);
      return;
    }
    clearTimeout(pending.timer);
    this.pendingExport = null;
    if (message.ok !== true) {
      const error = new Error(message.message || message.code || 'export failed');
      error.code = message.code || 'selected_target_export_failed';
      error.statusCode = error.code === 'export_in_progress' ? 409 : 422;
      pending.reject(error);
      return;
    }
    pending.resolve({
      path: message.path,
      metadata: {
        schema: message.schema,
        frame_id: message.frame_id,
        length_unit: message.length_unit,
        point_frame: message.point_frame,
      },
    });
  }

  exportSelectedTarget() {
    if (this.pendingExport) {
      const error = new Error('selected-target export already in progress');
      error.code = 'export_in_progress';
      error.statusCode = 409;
      return Promise.reject(error);
    }
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pendingExport?.requestId !== requestId) return;
        this.pendingExport = null;
        const error = new Error('selected-target export timed out');
        error.code = 'export_timeout';
        error.statusCode = 504;
        reject(error);
      }, this.exportTimeoutMs);
      timer.unref();
      this.pendingExport = { requestId, resolve, reject, timer };
      if (!this.send({ type: 'export_selected_target', requestId })) {
        clearTimeout(timer);
        this.pendingExport = null;
        const error = new Error('camera bridge is unavailable');
        error.code = 'camera_unavailable';
        error.statusCode = 503;
        reject(error);
      }
    });
  }

  _handleRawExportResult(message) {
    const pending = this.pendingRawExport;
    if (!pending || pending.requestId !== message.requestId) {
      this._removeExport(message.path);
      return;
    }
    clearTimeout(pending.timer);
    this.pendingRawExport = null;
    if (message.ok !== true) {
      const error = new Error(message.message || message.code || 'raw export failed');
      error.code = message.code || 'raw_frame_export_failed';
      error.statusCode = error.code === 'export_in_progress' ? 409 : 422;
      pending.reject(error);
      return;
    }
    pending.resolve({ path: message.path, metadata: {
      schema: message.schema, frame_id: message.frame_id,
      length_unit: message.length_unit, point_frame: message.point_frame,
    }});
  }

  exportRawFrame() {
    if (this.pendingRawExport) {
      const error = new Error('raw-frame export already in progress');
      error.code = 'export_in_progress'; error.statusCode = 409;
      return Promise.reject(error);
    }
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pendingRawExport?.requestId !== requestId) return;
        this.pendingRawExport = null;
        const error = new Error('raw-frame export timed out');
        error.code = 'export_timeout'; error.statusCode = 504;
        reject(error);
      }, this.exportTimeoutMs);
      timer.unref();
      this.pendingRawExport = { requestId, resolve, reject, timer };
      if (!this.send({ type: 'export_raw_frame', requestId })) {
        clearTimeout(timer); this.pendingRawExport = null;
        const error = new Error('camera bridge is unavailable');
        error.code = 'camera_unavailable'; error.statusCode = 503;
        reject(error);
      }
    });
  }

  _setProcessError(error) {
    this.meituanReady = false;
    this._status.camera = {
      ...this._status.camera,
      status: 'error',
      error: error.message,
    };
    this.emit('event', { type: 'runtime_status', ...this.status() });
  }

  status() {
    return {
      camera: { ...this._status.camera },
      inference: { ...this._status.inference },
      selection: { ...this._status.selection },
      detection: this.lastDetection,
      runtimeEvidence: this.runtimeEvidence
        ? { ...this.runtimeEvidence }
        : null,
    };
  }

  observation(stableId = null) {
    const detection = this.lastDetection;
    if (!detection || typeof detection !== 'object') return null;
    const targets = Array.isArray(detection.targets) ? detection.targets : [];
    const target = stableId === null ? null : targets.find(item => (
      Number(item.stableId ?? item.stable_id) === stableId
    ));
    if (stableId !== null && !target) return null;
    return {
      schema: detection.schema || 'thirdhand.vision-observation.v1',
      frameId: detection.frame_id ?? detection.sequence ?? null,
      observedAtMs: detection.ts ?? null,
      monotonicNs: detection.monotonic_ns ?? null,
      selectedStableId: detection.selected_stable_id
        ?? detection.selectedStableId ?? null,
      status: detection.status || 'observed',
      reasons: Array.isArray(detection.reasons) ? [...detection.reasons] : [],
      pose: detection.pose || null,
      target: target ? { ...target } : null,
      targets: targets.map(item => ({ ...item })),
      robotControlEnabled: false,
    };
  }

  subscribe(kind, response) {
    const stream = this.streams[kind];
    if (!stream) return false;
    const wasIdle = stream.subscriberCount() === 0;
    const subscribed = stream.subscribe(response);
    if (subscribed && wasIdle) this._setStreamEnabled(kind, true);
    return subscribed;
  }

  unsubscribe(kind, response) {
    const stream = this.streams[kind];
    if (!stream) return false;
    const removed = stream.unsubscribe(response);
    if (removed && stream.subscriberCount() === 0) {
      this._setStreamEnabled(kind, false);
    }
    return removed;
  }

  _setStreamEnabled(kind, enabled) {
    return this.send({
      type: 'set_stream_enabled',
      kind,
      enabled,
    });
  }

  send(message) {
    if (!this.child?.stdin?.writable || this.child.stdin.destroyed) return false;
    const allowed = new Set([
      'select_target', 'release_target', 'set_stream_enabled', 'arm_state', 'shutdown',
      'export_selected_target', 'export_raw_frame', 'meituan_detect', 'meituan_cancel',
    ]);
    if (!allowed.has(message?.type)) return false;
    if (message.type === 'meituan_detect' || message.type === 'meituan_cancel') {
      if (typeof message.sessionId !== 'string' || !message.sessionId || message.sessionId.length > 128) return false;
      if (message.type === 'meituan_detect' &&
          (typeof message.requestId !== 'string' || !message.requestId || message.requestId.length > 128 ||
           !message.parameters || typeof message.parameters !== 'object' || Array.isArray(message.parameters))) return false;
    }
    if (message.type === 'set_stream_enabled' &&
        (!Object.hasOwn(this.streams, message.kind) ||
         typeof message.enabled !== 'boolean')) return false;
    if (message.type === 'select_target' &&
        (!Number.isSafeInteger(message.stableId) ||
         message.stableId < 1 || message.stableId > 5)) {
      return false;
    }
    if (message.type === 'arm_state' && (
      message.pose_frame !== 'robot_flange' || message.connected !== true ||
      message.healthy !== true || typeof message.stationary !== 'boolean' ||
      ![message.flange_position_m, message.flange_euler_rad].every(
        value => Array.isArray(value) && value.length === 3 &&
          value.every(Number.isFinite)
      ) || !Array.isArray(message.joints_deg) || message.joints_deg.length !== 6 ||
      !message.joints_deg.every(Number.isFinite) ||
      !Number.isSafeInteger(message.observed_monotonic_ns) ||
      message.observed_monotonic_ns < 0
    )) return false;
    return this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  async close() {
    this.closing = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    for (const stream of Object.values(this.streams)) stream.close();
    if (this.pendingExport) {
      const pending = this.pendingExport;
      clearTimeout(pending.timer);
      this.pendingExport = null;
      const error = new Error('vision service is closing');
      error.code = 'camera_unavailable';
      error.statusCode = 503;
      pending.reject(error);
    }
    const child = this.child;
    if (!child) return;
    this.send({ type: 'shutdown' });
    await new Promise(resolve => {
      const timer = setTimeout(() => {
        if (child.exitCode === null) child.kill('SIGTERM');
      }, 1000);
      timer.unref();
      child.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
    if (this.child === child) this.child = null;
  }
}

module.exports = { CameraProcess, LatestMjpegBroadcaster, buildBridgeArgs };
