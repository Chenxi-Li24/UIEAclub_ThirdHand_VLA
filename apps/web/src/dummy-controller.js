'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

function failure(code) {
  return Object.assign(new Error(code), { code });
}

async function fetchJson(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(1500), redirect: 'error' });
  if (!response.ok) throw failure('dummy_upstream_unavailable');
  const reader = response.body.getReader();
  const chunks = [];
  let bytes = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes += value.length;
      if (bytes > 2 * 1024 * 1024) throw failure('dummy_response_too_large');
      chunks.push(Buffer.from(value));
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally {
    await reader.cancel().catch(() => {});
  }
}

class DummyController {
  constructor(config, options = {}) {
    this.config = config;
    this.platform = options.platform || process.platform;
    this.spawn = options.spawn || spawn;
    this.fetchJson = options.fetchJson || fetchJson;
    this.exists = options.exists || fs.existsSync;
    this.child = null;
    this.phase = 'stopped';
    this.reason = null;
    this.keywords = true;
    this.starting = false;
    this.closed = false;
    this.exitPromise = null;
    this.robotUrl = new URL('/health', config.robotWsUrl);
    this.robotUrl.protocol = this.robotUrl.protocol === 'wss:' ? 'https:' : 'http:';
    this.telemetryUrl = `http://127.0.0.1:${config.dummy.telemetryPort}`;
  }

  availability() {
    if (this.platform !== 'linux') return 'dummy_requires_ubuntu';
    const d = this.config.dummy;
    for (const [key, name] of [['python', 'python'], ['entry', 'entry'], ['urdf', 'urdf'], ['faceModel', 'face_model']]) {
      if (!this.exists(d[key])) return `dummy_${name}_missing`;
    }
    return null;
  }

  async observation() {
    try {
      const value = await this.fetchJson(`${this.telemetryUrl}/api/status`);
      return value.schema === 'thirdhand-dummy-live-observation-v1' ? value : null;
    } catch { return null; }
  }

  async status() {
    const unavailable = this.availability();
    const [observation, health] = await Promise.all([
      this.observation(), this.fetchJson(this.robotUrl.href).catch(() => null),
    ]);
    const owned = Boolean(this.child && observation?.pid === this.child.pid
      && observation.project_root === this.config.dummy.root);
    const external = Boolean(observation && !owned);
    const phase = external ? 'external' : this.child
      ? this.phase === 'stopping' ? 'stopping' : observation?.frame_id != null ? 'running' : 'starting'
      : this.phase;
    return {
      available: !unavailable, phase, running: Boolean(this.child || observation),
      pid: this.child?.pid || observation?.pid || null, owned,
      keywordsEnabled: this.keywords, reason: external ? 'dummy_external_process' : this.reason || unavailable,
      robot: health?.robot || null, observation: owned ? observation : null,
      limits: health?.robot?.continuousFollow || null,
      backendReady: health?.robot?.continuousFollow?.j1MaxSpeedDegS === 50,
      yoloAvailable: this.exists(this.config.dummy.yoloModel),
    };
  }

  async start({ authorized, keywords }) {
    if (authorized !== true || typeof keywords !== 'boolean') throw failure('dummy_authorization_required');
    if (this.closed) throw failure('dummy_controller_closed');
    if (this.child || this.starting) throw failure('dummy_already_running');
    const unavailable = this.availability();
    if (unavailable) throw failure(unavailable);
    this.starting = true;
    let finishStart;
    this.startFinished = new Promise(resolve => { finishStart = resolve; });
    try {
      if (await this.observation()) throw failure('dummy_external_process');
      const health = await this.fetchJson(this.robotUrl.href).catch(() => null);
      const robot = health?.robot;
      if (!robot?.connected || !robot.stateReady || !Number.isFinite(robot.lastStateAt)
          || Date.now() - robot.lastStateAt > 500
          || robot.lastStateAt > Date.now() + 50) throw failure('dummy_robot_not_ready');
      if (robot.moving) throw failure('dummy_robot_busy');
      if (robot.continuousFollow?.j1MaxSpeedDegS !== 50) throw failure('dummy_backend_upgrade_required');
      const vision = await this.fetchJson(new URL('/health', this.config.visionHttpUrl).href).catch(() => null);
      if (!['ready', 'ok'].includes(vision?.status)) throw failure('dummy_vision_not_ready');
      const d = this.config.dummy;
      const args = [d.entry, '--enable-motion', '--robot-ws', this.config.robotWsUrl,
        '--robot-health', this.robotUrl.href, '--telemetry-port', String(d.telemetryPort)];
      if (!keywords) args.push('--no-keywords');
      if (this.closed) throw failure('dummy_controller_closed');
      fs.mkdirSync(path.dirname(d.logFile), { recursive: true });
      const log = fs.openSync(d.logFile, 'a');
      let child;
      try {
        child = this.spawn(d.python, args, {
          cwd: d.root, shell: false,
          env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONDONTWRITEBYTECODE: '1',
            DUMMY_URDF_PATH: d.urdf, DUMMY_FACE_MODEL: d.faceModel, DUMMY_YOLO_MODEL: d.yoloModel,
            DUMMY_SPEECH_WS: d.speechWs, DUMMY_VISION_HTTP_URL: this.config.visionHttpUrl },
          stdio: ['ignore', log, log],
        });
      } finally { fs.closeSync(log); }
      this.child = child;
      this.phase = 'starting';
      this.reason = null;
      this.keywords = keywords;
      this.exitPromise = new Promise(resolve => {
        let ended = false;
        const finish = (code, signal, error) => {
          if (ended) return;
          ended = true;
          const requested = this.phase === 'stopping';
          this.child = null;
          this.phase = requested && !error && code === 0 ? 'stopped' : 'failed';
          this.reason = this.phase === 'failed' ? error?.code || `dummy_exit_${code ?? signal ?? 'unknown'}` : null;
          resolve();
        };
        child.once('error', error => finish(null, null, error));
        child.once('exit', (code, signal) => finish(code, signal));
      });
      return { phase: this.phase, running: true, pid: child.pid, keywordsEnabled: keywords };
    } finally { this.starting = false; finishStart(); }
  }

  stop() {
    if (this.starting && !this.child) throw failure('dummy_start_pending');
    if (this.child && this.phase !== 'stopping') {
      this.phase = 'stopping';
      this.reason = null;
      // Only the owned Dummy gets SIGTERM; never signal Robot, SDK, or camera.
      if (!this.child.kill('SIGTERM')) this.reason = 'dummy_stop_signal_failed';
    }
    return { phase: this.phase, running: Boolean(this.child), pid: this.child?.pid || null };
  }

  async frame() {
    if (!this.child || this.phase === 'stopping') throw failure('dummy_not_running');
    const packet = await this.fetchJson(`${this.telemetryUrl}/api/frame`);
    if (packet.state?.pid !== this.child.pid || packet.state?.project_root !== this.config.dummy.root) {
      throw failure('dummy_frame_owner_mismatch');
    }
    return packet;
  }

  async close() {
    this.closed = true;
    if (this.startFinished) await this.startFinished;
    this.stop();
    if (!this.exitPromise) return;
    let timer;
    try {
      await Promise.race([this.exitPromise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(failure('dummy_shutdown_unconfirmed')), 60000);
      })]);
    } finally { clearTimeout(timer); }
  }
}

module.exports = { DummyController, fetchJson };
