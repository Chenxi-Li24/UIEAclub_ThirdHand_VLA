'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');
const os = require('os');

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

    const python = this.config.python || process.env.STARTOUCH_PYTHON || 'python3';
    const script = path.join(__dirname, 'camera_bridge.py');
    const calibFile = this.config.calibrationFile ||
      path.join(os.homedir(), 'calibration', 'd435_handeye_result.json');
    const yoloModel = this.config.yoloModel || path.join(__dirname, 'yolov8n.pt');

    const env = {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      CAMERA_CALIB_FILE: calibFile,
      CAMERA_YOLO_MODEL: yoloModel,
      CAMERA_DETECT_INTERVAL: String(this.config.detectionInterval || 10),
      CAMERA_JPEG_QUALITY: String(this.config.jpegQuality || 70),
      CAMERA_DESK_Z: String(this.config.deskZ || 0.0),
      CAMERA_SAFE_Z: String(this.config.safeZ || 0.12),
      CAMERA_EVENT_FD: '3',
    };

    this.stopping = false;
    this.child = spawn(python, ['-u', script], {
      cwd: __dirname,
      env,
      stdio: ['pipe', 'pipe', 'pipe', 'pipe'],  // stdin, stdout(MJPEG D435), stderr, fd:3(events)
    });

    const child = this.child;

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

  /** Get the MJPEG stream (child's stdout) for HTTP piping */
  getMjpegStream() {
    return this.child ? this.child.stdout : null;
  }

  /** Send a command to the Python camera bridge via stdin */
  send(message) {
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
