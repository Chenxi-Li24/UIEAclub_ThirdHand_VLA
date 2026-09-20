'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const { createHash } = require('crypto');
const readline = require('readline');
const path = require('path');

const COMMAND_KEYS = {
  arm_state: [
    'type', 'pose_frame', 'flange_position_m', 'flange_euler_rad', 'joints_deg',
    'velocities_deg_s', 'stationary', 'observed_monotonic_ns',
  ],
  select_bottle: ['type', 'stable_id', 'request_id'],
  release_bottle: ['type', 'request_id'],
  reset_target_pose_reference: ['type', 'request_id', 'motion_epoch'],
};

function hasExactKeys(message, expected) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) return false;
  const actual = Object.keys(message).sort();
  const required = [...expected].sort();
  return actual.length === required.length
    && actual.every((value, index) => value === required[index]);
}

const MODEL_EVIDENCE_FIELDS = Object.freeze([
  'vision_config_id', 'camera_registration_id', 'camera_mount_id',
  'grounding_model', 'grounding_revision', 'grounding_weights_sha256',
  'sam_model', 'sam_revision', 'sam_weights_sha256',
]);

function sameModelEvidence(left, right) {
  return left && right && MODEL_EVIDENCE_FIELDS.every(field => left[field] === right[field]);
}

function detectionMatchesRuntime(message, runtime) {
  if (!runtime || message.schema !== 'thirdhand-va-detection-v3' ||
      !Number.isSafeInteger(message.frame_id) || message.frame_id < 0 ||
      !Number.isSafeInteger(message.monotonic_ns) || message.monotonic_ns < 0 ||
      message.camera_serial !== runtime.camera_serial ||
      message.registration_id !== runtime.registration_id ||
      !sameModelEvidence(message.model_provenance, runtime.model_provenance) ||
      !Array.isArray(message.targets)) return false;
  return message.targets.every(target => {
    const preview = target?.grasp_preview;
    return preview === undefined || (
      preview?.calibration_id === runtime.calibration_id &&
      preview.vision_config_id === runtime.vision_config_id &&
      sameModelEvidence(preview.model_provenance, runtime.model_provenance)
    );
  });
}

class OverlaySnapshotAssembler {
  constructor({ maxJpegBytes = 2 * 1024 * 1024, maxPendingEntries = 8 } = {}) {
    if (!Number.isSafeInteger(maxJpegBytes) || maxJpegBytes < 4 ||
        maxJpegBytes > 2 * 1024 * 1024) {
      throw new TypeError('maxJpegBytes must be an integer within [4, 2097152]');
    }
    if (!Number.isSafeInteger(maxPendingEntries) || maxPendingEntries < 1 ||
        maxPendingEntries > 32) {
      throw new TypeError('maxPendingEntries must be an integer within [1, 32]');
    }
    this.maxJpegBytes = maxJpegBytes;
    this.maxPendingEntries = maxPendingEntries;
    this.buffer = Buffer.alloc(0);
    this.detections = new Map();
    this.overlays = new Map();
    this.snapshot = null;
  }

  noteDetection(event) {
    if (!event || event.type !== 'detection_result' ||
        !Number.isSafeInteger(event.frame_id) || event.frame_id < 0 ||
        !Number.isSafeInteger(event.monotonic_ns) || event.monotonic_ns < 0 ||
        !Number.isSafeInteger(event.ts) || event.ts < 0) {
      return false;
    }
    const provenance = Object.freeze({
      frameId: event.frame_id,
      frameMonotonicNs: event.monotonic_ns,
      observedAtMs: event.ts,
    });
    const key = this._key(provenance);
    this._remember(this.detections, key, provenance);
    this._publishIfComplete(key);
    return true;
  }

  push(chunk) {
    if (!Buffer.isBuffer(chunk) && !(chunk instanceof Uint8Array)) return;
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    while (this.buffer.length) {
      const start = this.buffer.indexOf(Buffer.from('--frame\r\n'));
      if (start < 0) {
        this.buffer = this.buffer.subarray(Math.max(0, this.buffer.length - 9));
        return;
      }
      if (start > 0) this.buffer = this.buffer.subarray(start);
      const headerEnd = this.buffer.indexOf(Buffer.from('\r\n\r\n'), 9);
      if (headerEnd < 0) {
        if (this.buffer.length > 4096) this.buffer = Buffer.alloc(0);
        return;
      }
      const headers = this._parseHeaders(this.buffer.subarray(9, headerEnd).toString('ascii'));
      if (headers === null) {
        this.buffer = this.buffer.subarray(headerEnd + 4);
        continue;
      }
      const frameEnd = headerEnd + 4 + headers.contentLength;
      if (this.buffer.length < frameEnd + 2) return;
      const jpeg = Buffer.from(this.buffer.subarray(headerEnd + 4, frameEnd));
      const trailer = this.buffer.subarray(frameEnd, frameEnd + 2);
      this.buffer = this.buffer.subarray(frameEnd + 2);
      if (!trailer.equals(Buffer.from('\r\n'))) continue;
      const digest = `sha256:${createHash('sha256').update(jpeg).digest('hex')}`;
      if (digest !== headers.imageSha256) continue;
      const key = this._key(headers);
      this._remember(this.overlays, key, Object.freeze({ ...headers, jpeg }));
      this._publishIfComplete(key);
    }
  }

  _parseHeaders(raw) {
    const values = new Map();
    for (const line of raw.split('\r\n')) {
      const separator = line.indexOf(':');
      if (separator < 1) return null;
      values.set(line.slice(0, separator).trim().toLowerCase(), line.slice(separator + 1).trim());
    }
    if (values.get('content-type') !== 'image/jpeg') return null;
    const integer = name => {
      const value = values.get(name);
      if (!value || !/^(0|[1-9][0-9]*)$/.test(value)) return null;
      const parsed = Number(value);
      return Number.isSafeInteger(parsed) ? parsed : null;
    };
    const contentLength = integer('content-length');
    const frameId = integer('x-thirdhand-frame-id');
    const frameMonotonicNs = integer('x-thirdhand-monotonic-ns');
    const observedAtMs = integer('x-thirdhand-observed-at-ms');
    const imageSha256 = values.get('x-thirdhand-image-sha256');
    if (contentLength === null || contentLength < 4 || contentLength > this.maxJpegBytes ||
        frameId === null || frameMonotonicNs === null || observedAtMs === null ||
        !/^sha256:[0-9a-f]{64}$/.test(imageSha256 || '')) {
      return null;
    }
    return { contentLength, frameId, frameMonotonicNs, observedAtMs, imageSha256 };
  }

  _key({ frameId, frameMonotonicNs, observedAtMs }) {
    return `${frameId}:${frameMonotonicNs}:${observedAtMs}`;
  }

  _remember(map, key, value) {
    map.delete(key);
    map.set(key, value);
    while (map.size > this.maxPendingEntries) map.delete(map.keys().next().value);
  }

  _publishIfComplete(key) {
    const detection = this.detections.get(key);
    const overlay = this.overlays.get(key);
    if (!detection || !overlay) return;
    this.snapshot = Object.freeze({
      ...detection,
      imageSha256: overlay.imageSha256,
      jpeg: Buffer.from(overlay.jpeg),
    });
    this.detections.delete(key);
    this.overlays.delete(key);
  }

  latest() {
    if (this.snapshot === null) return null;
    return { ...this.snapshot, jpeg: Buffer.from(this.snapshot.jpeg) };
  }

  reset() {
    this.buffer = Buffer.alloc(0);
    this.detections.clear();
    this.overlays.clear();
    this.snapshot = null;
  }
}

/**
 * Frame-aligned, non-blocking MJPEG fan-out.
 *
 * The camera child is always drained. A slow browser owns at most one pending
 * latest frame, so HTTP backpressure can never pause perception or another
 * viewer. This is the same latest-value policy used by live video/pub-sub
 * systems where latency matters more than delivering every historical frame.
 */
class LatestMjpegBroadcaster {
  constructor({ maxPartBytes = 3 * 1024 * 1024 } = {}) {
    if (!Number.isSafeInteger(maxPartBytes) || maxPartBytes < 1024 ||
        maxPartBytes > 8 * 1024 * 1024) {
      throw new TypeError('maxPartBytes must be within [1024, 8388608]');
    }
    this.maxPartBytes = maxPartBytes;
    this.boundary = Buffer.from('--frame\r\n');
    this.headerTerminator = Buffer.from('\r\n\r\n');
    this.buffer = Buffer.alloc(0);
    this.latest = null;
    this.clients = new Map();
  }

  push(chunk) {
    if (!Buffer.isBuffer(chunk) && !(chunk instanceof Uint8Array)) return;
    this.buffer = Buffer.concat([this.buffer, Buffer.from(chunk)]);
    while (this.buffer.length) {
      const start = this.buffer.indexOf(this.boundary);
      if (start < 0) {
        this.buffer = this.buffer.subarray(
          Math.max(0, this.buffer.length - this.boundary.length + 1)
        );
        return;
      }
      if (start > 0) this.buffer = this.buffer.subarray(start);
      const headerEnd = this.buffer.indexOf(this.headerTerminator, this.boundary.length);
      if (headerEnd < 0) {
        if (this.buffer.length > 8192) this.buffer = Buffer.alloc(0);
        return;
      }
      const rawHeaders = this.buffer
        .subarray(this.boundary.length, headerEnd)
        .toString('ascii');
      const match = rawHeaders.match(/(?:^|\r\n)Content-Length:\s*(\d+)\s*(?:\r\n|$)/i);
      if (!match) {
        this.buffer = this.buffer.subarray(headerEnd + this.headerTerminator.length);
        continue;
      }
      const contentLength = Number(match[1]);
      if (!Number.isSafeInteger(contentLength) || contentLength < 4 ||
          contentLength > this.maxPartBytes) {
        this.buffer = Buffer.alloc(0);
        return;
      }
      const partEnd = headerEnd + this.headerTerminator.length + contentLength + 2;
      if (this.buffer.length < partEnd) return;
      if (!this.buffer.subarray(partEnd - 2, partEnd).equals(Buffer.from('\r\n'))) {
        this.buffer = this.buffer.subarray(this.boundary.length);
        continue;
      }
      const part = Buffer.from(this.buffer.subarray(0, partEnd));
      this.buffer = this.buffer.subarray(partEnd);
      this.latest = part;
      this._broadcast(part);
    }
  }

  subscribe(response) {
    if (!response || typeof response.write !== 'function' ||
        typeof response.on !== 'function') return false;
    if (this.clients.has(response)) return true;
    const state = { blocked: false, pending: null, onDrain: null };
    state.onDrain = () => {
      state.blocked = false;
      const pending = state.pending;
      state.pending = null;
      if (pending && this.clients.has(response)) this._write(response, state, pending);
    };
    response.on('drain', state.onDrain);
    this.clients.set(response, state);
    if (this.latest) this._write(response, state, this.latest);
    return true;
  }

  unsubscribe(response) {
    const state = this.clients.get(response);
    if (!state) return false;
    this.clients.delete(response);
    state.pending = null;
    response.removeListener?.('drain', state.onDrain);
    return true;
  }

  reset() {
    this.buffer = Buffer.alloc(0);
    this.latest = null;
    for (const [response, state] of this.clients) {
      response.removeListener?.('drain', state.onDrain);
      if (!response.destroyed) response.end?.();
    }
    this.clients.clear();
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
      if (response.write(part) === false) state.blocked = true;
    } catch {
      this.unsubscribe(response);
    }
  }
}

class CameraBridge extends EventEmitter {
  constructor(config) {
    super();
    this.config = config || {};
    this.child = null;
    this.ready = false;
    this.streaming = false;
    this.runtimeEvidence = null;
    this.lastProcessedAtMs = 0;
    this.stopping = false;
    this.restartTimer = null;
    this.overlaySnapshots = new OverlaySnapshotAssembler({
      maxJpegBytes: this.config.overlaySnapshotMaxJpegBytes || 2 * 1024 * 1024,
    });
    this.mjpeg = Object.freeze({
      primary: new LatestMjpegBroadcaster(),
      overlay: new LatestMjpegBroadcaster(),
      raw: new LatestMjpegBroadcaster(),
      depth: new LatestMjpegBroadcaster(),
    });
  }

  start() {
    if (this.child) return;

    const spec = this.buildSpawnSpec();

    this.stopping = false;
    this.child = spawn(spec.python, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      stdio: spec.stdio,
    });

    const child = this.child;

    // The Python bridge may exit after a camera timeout while arm-state updates
    // are still in flight. Node emits EPIPE on stdin asynchronously; handling it
    // here keeps the web/control server alive while the camera auto-restarts.
    child.stdin.on('error', error => {
      if (error && error.code === 'EPIPE') return;
      this.emit('bridge_error', {
        message: `Camera bridge stdin error: ${error && error.message ? error.message : error}`,
      });
    });

    // Keep both child video pipes drained even when no browser is connected.
    // Future HTTP pipe() consumers still receive all subsequent chunks.
    child.stdout.on('data', chunk => this.mjpeg.primary.push(chunk));
    child.stdio[4].on('data', chunk => {
      this.overlaySnapshots.push(chunk);
      this.mjpeg.overlay.push(chunk);
    });
    child.stdio[5].on('data', chunk => this.mjpeg.raw.push(chunk));
    child.stdio[6].on('data', chunk => this.mjpeg.depth.push(chunk));

    // fd:4 → JSON events
    const eventLines = readline.createInterface({ input: child.stdio[3] });
    eventLines.on('line', line => this._handleLine(line));

    // stderr → log
    child.stderr.on('data', data => {
      const message = data.toString('utf8').trim();
      if (message) this.emit('log', { level: 'warning', message: `Camera: ${message}` });
    });

    child.on('error', error => {
      this.emit('bridge_error', { message: `Failed to start camera bridge: ${error.message}` });
    });

    child.on('exit', (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      this.ready = false;
      this.streaming = false;
      this.runtimeEvidence = null;
      this.lastProcessedAtMs = 0;
      this.overlaySnapshots.reset();
      for (const relay of Object.values(this.mjpeg)) relay.reset();
      this.emit('camera_status', {
        lumos_ready: false,
        calibration_loaded: false,
        reason: `bridge_exit:${signal || code}`,
      });
      if (!this.stopping) this._scheduleRestart();
    });
  }

  buildSpawnSpec() {
    const projectRoot = this.config.projectRoot || path.resolve(__dirname, '../../../..');
    const python = this.config.python || process.env.CAMERA_PYTHON ||
      process.env.STARTOUCH_PYTHON || 'python3';
    const moduleName = this.config.module || process.env.CAMERA_BRIDGE_MODULE ||
      'apps.bottle_pick.camera_bridge';
    if (moduleName !== 'apps.bottle_pick.camera_bridge') {
      throw new Error('Unsupported camera bridge module');
    }
    const xvisioStreamExecutable = this.config.xvisioStreamExecutable ||
      process.env.XVISIO_STREAM_EXECUTABLE ||
      path.resolve(projectRoot, 'build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream');
    const visionConfig = this.config.visionConfig || process.env.VISION_CONFIG ||
      path.resolve(projectRoot, 'configs/vision.yaml');
    const calibrationFile = this.config.calibrationFile ||
      process.env.THIRDHAND_VA_HANDEYE || null;
    const onlineEnabled = this.config.onlineEnabled === undefined
      ? process.env.VISION_ONLINE_ENABLED === '1'
      : Boolean(this.config.onlineEnabled);
    return {
      python,
      args: ['-u', '-m', moduleName],
      cwd: this.config.cwd || projectRoot,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        PYTHONPATH: [
          path.resolve(projectRoot, 'src'),
          process.env.PYTHONPATH,
        ].filter(Boolean).join(path.delimiter),
        CAMERA_JPEG_QUALITY: String(this.config.jpegQuality || 70),
        CAMERA_EVENT_FD: '3',
        VISION_OVERLAY_FD: '4',
        XVISIO_RAW_FD: '5',
        DEPTH_HEATMAP_FD: '6',
        DEPTH_HEATMAP_FPS: String(this.config.depthHeatmapFps || 10),
        VISION_ONLINE_ENABLED: onlineEnabled ? '1' : '0',
        VISION_CONFIG: visionConfig,
        THIRDHAND_VA_CONFIG: visionConfig,
        XVISIO_STREAM_EXECUTABLE: xvisioStreamExecutable,
        ...(calibrationFile === null ? {} : {
          THIRDHAND_VA_HANDEYE: path.resolve(projectRoot, calibrationFile),
        }),
      },
      stdio: ['pipe', 'pipe', 'pipe', 'pipe', 'pipe', 'pipe', 'pipe'],
    };
  }

  /** Get the MJPEG stream (child's stdout) for HTTP piping */
  getMjpegStream() {
    return this.child ? this.child.stdout : null;
  }

  /** Canonical Lumos overlay stream from the dedicated child fd 4. */
  getVisionMjpegStream() {
    return this.child && this.child.stdio ? this.child.stdio[4] : null;
  }

  /** Latest exactly paired ID-labelled overlay and detection provenance. */
  getLatestVisionSnapshot() {
    return this.overlaySnapshots.latest();
  }

  /** Raw XVisio RGB stream, independent from slower model inference. */
  getXVisioRawMjpegStream() {
    return this.child && this.child.stdio ? this.child.stdio[5] : null;
  }

  /** Throttled pseudo-colour metric-depth stream. */
  getDepthHeatmapMjpegStream() {
    return this.child && this.child.stdio ? this.child.stdio[6] : null;
  }

  /** Detach a browser without leaving the long-lived child pipe paused. */
  releaseMjpegStream(stream, destination) {
    if (!stream) return;
    try { stream.unpipe(destination); } catch (_) { /* already detached */ }
    stream.resume();
  }

  subscribeMjpeg(kind, response) {
    if (!this.child || !Object.hasOwn(this.mjpeg, kind)) return false;
    return this.mjpeg[kind].subscribe(response);
  }

  unsubscribeMjpeg(kind, response) {
    if (!Object.hasOwn(this.mjpeg, kind)) return false;
    return this.mjpeg[kind].unsubscribe(response);
  }

  /** Send a command to the Python camera bridge via stdin */
  send(message) {
    const command = message && (message.type || message.cmd);
    const allowed = [
      'arm_state',
      'get_status',
      'shutdown',
      'select_bottle',
      'release_bottle',
      'reset_target_pose_reference',
    ];
    if (!allowed.includes(command)) return false;
    if (command === 'select_bottle') {
      if (!hasExactKeys(message, COMMAND_KEYS.select_bottle) ||
          !Number.isSafeInteger(message.stable_id) || message.stable_id < 1 ||
          message.stable_id > 5 || typeof message.request_id !== 'string' ||
          message.request_id.length === 0) return false;
    } else if (command === 'release_bottle') {
      if (!hasExactKeys(message, COMMAND_KEYS.release_bottle) ||
          typeof message.request_id !== 'string' ||
          message.request_id.length === 0) return false;
    } else if (command === 'reset_target_pose_reference') {
      if (!hasExactKeys(message, COMMAND_KEYS.reset_target_pose_reference) ||
          typeof message.request_id !== 'string' || message.request_id.length === 0 ||
          !Number.isSafeInteger(message.motion_epoch) || message.motion_epoch < 1) return false;
    } else if (COMMAND_KEYS[command] && !hasExactKeys(message, COMMAND_KEYS[command])) {
      return false;
    }
    if (!this.child || !this.child.stdin || this.child.stdin.destroyed ||
        !this.child.stdin.writable || this.child.stdin.writableEnded) {
      this.emit('bridge_error', { message: 'Camera bridge not ready' });
      return false;
    }
    try {
      return this.child.stdin.write(`${JSON.stringify(message)}\n`);
    } catch (error) {
      if (!error || error.code !== 'EPIPE') {
        this.emit('bridge_error', {
          message: `Camera bridge write failed: ${error && error.message ? error.message : error}`,
        });
      }
      return false;
    }
  }

  /** Send arm state to the camera bridge for coordinate transforms */
  sendArmState(
    flangePosition,
    flangeEuler,
    jointsDeg,
    velocitiesDegS,
    stationary,
    observedAtNs
  ) {
    return this.send({
      type: 'arm_state',
      pose_frame: 'robot_flange',
      flange_position_m: flangePosition,
      flange_euler_rad: flangeEuler,
      joints_deg: jointsDeg,
      velocities_deg_s: velocitiesDegS,
      stationary,
      observed_monotonic_ns: observedAtNs,
    });
  }

  shutdown() {
    this.stopping = true;
    this.overlaySnapshots.reset();
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    if (this.child) {
      this.send({ cmd: 'shutdown' });
      const child = this.child;
      setTimeout(() => {
        if (this.child === child) child.kill('SIGTERM');
      }, 500).unref();
    }
  }

  getInfo() {
    const maxReadyAgeMs = this.config.maxReadyAgeMs || 2000;
    const ready = this.ready === true && this.lastProcessedAtMs > 0 &&
      Date.now() - this.lastProcessedAtMs <= maxReadyAgeMs;
    return {
      ready,
      streaming: this.streaming,
      calibrationFile: this.config.calibrationFile,
      yoloModel: this.config.yoloModel,
      runtimeEvidence: this.runtimeEvidence === null
        ? null : { ...this.runtimeEvidence },
      calibrationApproved: this.runtimeEvidence?.calibration_approved === true,
    };
  }

  _handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.emit('log', { level: 'warning', message: `Camera event parse error: ${line}` });
      return;
    }
    if (this.config.logEvents === true) {
      console.log(`[Camera event] type=${message.type}`);
    }
    if (message.type === 'bridge_ready') {
      const models = message.model_provenance;
      const valid = typeof message.camera_serial === 'string' &&
        message.camera_serial.length > 0 &&
        typeof message.registration_id === 'string' && message.registration_id.length > 0 &&
        typeof message.camera_mount_id === 'string' && message.camera_mount_id.length > 0 &&
        /^sha256:[0-9a-f]{64}$/.test(message.vision_config_id || '') &&
        models && models.vision_config_id === message.vision_config_id &&
        models.camera_registration_id === message.registration_id &&
        models.camera_mount_id === message.camera_mount_id &&
        typeof models.grounding_model === 'string' && models.grounding_model.length > 0 &&
        typeof models.sam_model === 'string' && models.sam_model.length > 0 &&
        /^[0-9a-f]{40}$/.test(models.grounding_revision || '') &&
        /^[0-9a-f]{40}$/.test(models.sam_revision || '') &&
        /^sha256:[0-9a-f]{64}$/.test(
          models.grounding_weights_sha256 || ''
        ) && /^sha256:[0-9a-f]{64}$/.test(models.sam_weights_sha256 || '') &&
        (message.calibration_approved !== true ||
          /^sha256:[0-9a-f]{64}$/.test(message.calibration_id || ''));
      this.ready = valid;
      this.streaming = valid;
      this.runtimeEvidence = valid ? Object.freeze({
        camera_serial: message.camera_serial,
        registration_id: message.registration_id,
        camera_mount_id: message.camera_mount_id,
        vision_config_id: message.vision_config_id,
        calibration_id: message.calibration_id,
        calibration_approved: message.calibration_approved === true,
        model_provenance: { ...models },
      }) : null;
      this.lastProcessedAtMs = valid ? Date.now() : 0;
    }
    if (message.type === 'camera_status' && message.lumos_ready) {
      this.streaming = true;
    }
    if (message.type === 'detection_result') {
      const runtime = this.runtimeEvidence;
      const matchesRuntime = detectionMatchesRuntime(message, runtime);
      if (matchesRuntime) {
        this.lastProcessedAtMs = Date.now();
        this.overlaySnapshots.noteDetection(message);
      } else {
        this.emit('detection_rejected', Object.freeze({
          type: 'detection_rejected', reason: 'runtime_artifact_mismatch',
          frame_id: Number.isSafeInteger(message.frame_id) ? message.frame_id : null,
          robot_control_enabled: false,
        }));
        return;
      }
    }
    this.emit(message.type, message);
    this.emit('message', message);
  }

  _scheduleRestart() {
    if (this.restartTimer) return;
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.stopping) this.start();
    }, 2000);
  }
}

module.exports = {
  CameraBridge, OverlaySnapshotAssembler, LatestMjpegBroadcaster,
  detectionMatchesRuntime,
};
