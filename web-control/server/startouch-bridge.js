'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');

class StartouchBridge extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.child = null;
    this.ready = false;
    this.connected = false;
    this.stopping = false;
    this.restartTimer = null;
    this.softwareStopTimer = null;
  }

  start() {
    if (this.child) return;

    const python = this.config.python;
    const script = path.join(__dirname, 'startouch_bridge.py');
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      STARTOUCH_SDK_PATH: this.config.sdkPath,
      STARTOUCH_CAN_INTERFACE: this.config.canInterface,
      STARTOUCH_GRIPPER: this.config.gripper ? '1' : '0',
      STARTOUCH_REQUIRE_CAN_RX: this.config.requireCanRx ? '1' : '0',
      STARTOUCH_CAN_RX_STALE_SEC: String(this.config.canRxStaleSec),
      STARTOUCH_SIMULATE: this.config.simulate ? '1' : '0',
      STARTOUCH_DRY_RUN: this.config.dryRun ? '1' : '0',
      STARTOUCH_POLL_INTERVAL_MS: String(this.config.pollIntervalMs),
      STARTOUCH_JOINT_LOG_INTERVAL_MS: String(this.config.jointLogIntervalMs),
      STARTOUCH_INIT_SETTLE_SEC: String(this.config.initSettleSec),
      STARTOUCH_INIT_SAMPLE_COUNT: String(this.config.initSampleCount),
      STARTOUCH_INIT_MAX_DRIFT_DEG: String(this.config.initMaxDriftDeg),
      STARTOUCH_EVENT_FD: '3',
    };

    this.stopping = false;
    this.child = spawn(python, ['-u', script], {
      cwd: this.config.simulate ? __dirname : this.config.sdkPath,
      env,
      stdio: ['pipe', 'pipe', 'pipe', 'pipe'],
    });

    const child = this.child;
    const lines = readline.createInterface({ input: child.stdio[3] });
    lines.on('line', line => this._handleLine(line));
    const sdkLines = readline.createInterface({ input: child.stdout });
    sdkLines.on('line', line => {
      if (line.trim()) this.emit('log', { level: 'info', message: `SDK: ${line}` });
    });
    child.stderr.on('data', data => {
      const message = data.toString('utf8').trim();
      if (message) this.emit('log', { level: 'warning', message });
    });
    child.on('error', error => {
      this.emit('bridge_error', { message: `无法启动 Python SDK 桥接: ${error.message}` });
    });
    child.on('exit', (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      this.ready = false;
      this.connected = false;
      this.emit('connection', {
        connected: false,
        interface: this.config.canInterface,
        reason: `bridge_exit:${signal || code}`,
      });
      if (!this.stopping) this._scheduleRestart();
    });
  }

  send(message) {
    if (!this.child || !this.child.stdin.writable) {
      this.emit('bridge_error', { message: 'Python SDK 桥接尚未就绪' });
      return false;
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return true;
  }

  softwareStop() {
    if (!this.child || !this.connected) return false;
    const child = this.child;
    if (!this.send({ cmd: 'software_stop' })) return false;

    if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
    this.softwareStopTimer = setTimeout(() => {
      this.softwareStopTimer = null;
      if (this.child !== child || !this.connected) return;
      this.emit('software_stop_timeout', {
        message: 'SDK cleanup 超时，无法确认电机已失能；正在强制终止控制进程',
      });
      child.kill('SIGTERM');
      setTimeout(() => {
        if (this.child === child) child.kill('SIGKILL');
      }, 500).unref();
    }, 2000);
    this.softwareStopTimer.unref();
    return true;
  }

  shutdown() {
    this.stopping = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
    this.softwareStopTimer = null;
    if (this.child) {
      this.send({ cmd: 'shutdown' });
      const child = this.child;
      setTimeout(() => {
        if (this.child === child) child.kill('SIGTERM');
      }, 300).unref();
    }
  }

  getInfo() {
    return {
      mode: 'startouch',
      host: 'localhost',
      interface: this.config.canInterface,
      connected: this.connected,
      ready: this.ready,
      simulated: this.config.simulate,
      dryRun: this.config.dryRun,
    };
  }

  _handleLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      this.emit('log', { level: 'warning', message: `桥接事件无法解析: ${line}` });
      return;
    }
    if (message.type === 'bridge_ready') this.ready = true;
    if (message.type === 'connection') {
      this.connected = Boolean(message.connected);
      if (!message.connected && message.reason === 'software_stop') {
        if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
        this.softwareStopTimer = null;
        this.emit('software_stop_complete', message);
      }
    }
    this.emit(message.type, message);
    this.emit('message', message);
  }

  _scheduleRestart() {
    if (this.restartTimer) return;
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      this.start();
    }, 1000);
  }
}

module.exports = { StartouchBridge };
