'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

class CameraBridge extends EventEmitter {
  constructor(config) {
    super();
    this.config = config || {};
    this.child = null;
    this.ready = false;
    this.streaming = false;
    this.stopping = false;
    this.restartTimer = null;
  }

  start() {
    if (this.child) return;

    // Ensure D435 USB power is always on (prevents "failed to set power state")
    const { execSync } = require('child_process');
    try {
      execSync('for d in /sys/bus/usb/devices/*/idVendor; do d=$(dirname "$d"); [ "$(cat "$d/idVendor" 2>/dev/null)$(cat "$d/idProduct" 2>/dev/null)" = "80860b07" ] && echo on | sudo -n tee "$d/power/control" > /dev/null 2>&1 && echo -1 | sudo -n tee "$d/power/autosuspend" > /dev/null 2>&1; done', { timeout: 3000 });
    } catch (_) { /* sudo -n may fail if not passwordless, ignore */ }

    const spec = this.buildSpawnSpec();

    this.stopping = false;
    this.child = spawn(spec.python, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      stdio: spec.stdio,
    });

    const child = this.child;

    // Keep both child video pipes drained even when no browser is connected.
    // Future HTTP pipe() consumers still receive all subsequent chunks.
    child.stdout.on('data', () => {});
    child.stdio[4].on('data', () => {});

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
      this.emit('camera_status', {
        d435_ready: false,
        calibration_loaded: false,
        reason: `bridge_exit:${signal || code}`,
      });
      if (!this.stopping) this._scheduleRestart();
    });
  }

  buildSpawnSpec() {
    const python = this.config.python || process.env.CAMERA_PYTHON ||
      process.env.STARTOUCH_PYTHON || 'python3';
    const script = path.join(__dirname, 'camera_bridge.py');
    const visionConfig = this.config.visionConfig || process.env.VISION_CONFIG ||
      path.resolve(__dirname, '../../configs/vision/remind3d.yaml');
    const lumosSnapshotUrl = this.config.lumosSnapshotUrl ||
      process.env.LUMOS_SNAPSHOT_URL || 'http://127.0.0.1:3001/frame.jpg';
    const onlineEnabled = this.config.onlineEnabled === undefined
      ? process.env.VISION_ONLINE_ENABLED === '1'
      : Boolean(this.config.onlineEnabled);
    return {
      python,
      args: ['-u', script],
      cwd: __dirname,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        CAMERA_JPEG_QUALITY: String(this.config.jpegQuality || 70),
        CAMERA_EVENT_FD: '3',
        VISION_OVERLAY_FD: '4',
        VISION_ONLINE_ENABLED: onlineEnabled ? '1' : '0',
        VISION_CONFIG: visionConfig,
        LUMOS_SNAPSHOT_URL: lumosSnapshotUrl,
      },
      stdio: ['pipe', 'pipe', 'pipe', 'pipe', 'pipe'],
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

  /** Detach a browser without leaving the long-lived child pipe paused. */
  releaseMjpegStream(stream, destination) {
    if (!stream) return;
    try { stream.unpipe(destination); } catch (_) { /* already detached */ }
    stream.resume();
  }

  /** Send a command to the Python camera bridge via stdin */
  send(message) {
    const command = message && (message.type || message.cmd);
    if (!['arm_state', 'get_status', 'shutdown'].includes(command)) return false;
    if (!this.child || !this.child.stdin.writable) {
      this.emit('bridge_error', { message: 'Camera bridge not ready' });
      return false;
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return true;
  }

  /** Send arm state to the camera bridge for coordinate transforms */
  sendArmState(tcpPosition, tcpEuler) {
    return this.send({
      type: 'arm_state',
      tcp_position_m: tcpPosition,
      tcp_euler_rad: tcpEuler,
    });
  }

  shutdown() {
    this.stopping = true;
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
    return {
      ready: this.ready,
      streaming: this.streaming,
      calibrationFile: this.config.calibrationFile,
      yoloModel: this.config.yoloModel,
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
    console.log(`[Camera event] type=${message.type}`);
    if (message.type === 'bridge_ready') {
      this.ready = true;
      this.streaming = true;
    }
    if (message.type === 'camera_status' && message.d435_ready) {
      this.streaming = true;
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

module.exports = { CameraBridge };
