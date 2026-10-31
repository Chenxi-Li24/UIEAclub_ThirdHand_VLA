'use strict';

const { EventEmitter } = require('events');
const { spawn } = require('child_process');
const readline = require('readline');
const path = require('path');
const { randomUUID } = require('node:crypto');
const LEASE_UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const LEASE_BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId','hardwareFingerprint','leaseId','leaseEpoch'];
const LEASE_FIELDS=[...LEASE_BINDING,'sequence','issuedAt','expiresAt'];
const GUARDED_COMMANDS=new Set(['connect','move_joint','move_joint_path','fixed_tcp_demo','move_l','go_home','gripper','preview_ik','follow_start','follow_target','follow_stop']);

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
    this.pendingSoftwareStopId = null;
    this.remoteLease = null;
    this.remoteLeaseEpoch = 0;
    this.remoteLeaseAnchor = null;
    this.remoteLeaseDeadline = null;
    this.remoteLeaseWorkerReady = false;
  }

  start() {
    if (this.child) return;

    const python = this.config.python;
    const script = path.join(__dirname, 'startouch_bridge.py');
    const env = {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      STARTOUCH_SDK_PATH: this.config.sdkPath,
      STARTOUCH_MODULE_PATH: this.config.modulePath || '',
      STARTOUCH_CAN_INTERFACE: this.config.canInterface,
      STARTOUCH_GRIPPER: this.config.gripper ? '1' : '0',
      STARTOUCH_REQUIRE_CAN_RX: this.config.requireCanRx ? '1' : '0',
      STARTOUCH_CAN_RX_STALE_SEC: String(this.config.canRxStaleSec),
      STARTOUCH_SIMULATE: this.config.simulate ? '1' : '0',
      STARTOUCH_DRY_RUN: this.config.dryRun ? '1' : '0',
      STARTOUCH_REMOTE_LEASE_GUARD: this.config.remoteLeaseGuard === true ? '1' : '0',
      STARTOUCH_POLL_INTERVAL_MS: String(this.config.pollIntervalMs),
      STARTOUCH_JOINT_LOG_INTERVAL_MS: String(this.config.jointLogIntervalMs),
      STARTOUCH_INIT_SETTLE_SEC: String(this.config.initSettleSec),
      STARTOUCH_INIT_SAMPLE_COUNT: String(this.config.initSampleCount),
      STARTOUCH_INIT_MAX_DRIFT_DEG: String(this.config.initMaxDriftDeg),
      STARTOUCH_SPEED_SCALE: String(Math.min(0.10, this.config.speedScale ?? 0.05)),
      STARTOUCH_FOLLOW_J1_MAX_SPEED_DEG_S: String(this.config.followJ1MaxSpeedDegS ?? 50),
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
      this._handleExit(child, code, signal);
    });
  }

  _handleExit(child, code, signal) {
    if (this.child !== child) return;
    this.child = null;
    this.ready = false;
    this.connected = false;
    this.remoteLease = null;
    this.remoteLeaseDeadline = null;
    this.remoteLeaseWorkerReady = false;
    if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
    this.softwareStopTimer = null;
    const requestId = this.pendingSoftwareStopId;
    this.pendingSoftwareStopId = null;
    if (requestId) this.emit('software_stop_result', {
      request_id: requestId, sdk_released: false, cleanup_state: 'unconfirmed',
      stop_state: 'unknown', stop_code: 'WORKER_EXIT_UNCONFIRMED',
      source_mode: this.config.simulate ? 'simulation' : this.config.dryRun ? 'dry-run' : 'hardware',
    });
    const message = {
      type: 'connection', connected: false,
      interface: this.config.canInterface, reason: `bridge_exit:${signal || code}`,
      sdk_released: false, stop_state: 'unknown',
    };
    this.emit('connection', message);
    this.emit('message', message);
    if (!this.stopping) this._scheduleRestart();
  }

  send(message) {
    if (!this.child || !this.child.stdin.writable) {
      this.emit('bridge_error', { message: 'Python SDK 桥接尚未就绪' });
      return false;
    }
    if (this.config.remoteLeaseGuard === true && GUARDED_COMMANDS.has(message.cmd)) {
      if (!this._remoteLeaseLive()) {
        this.emit('bridge_error', { code: 'remote_lease_required', request_id: message.request_id,
          message: 'Current worker lease required for SDK command' });
        return false;
      }
      // Bind each queued command to the original signed lease, rather than
      // letting a later lease authorize work waiting in a pipe/motion queue.
      message = {...message, remote_lease: {...this.remoteLease}};
    }
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return true;
  }

  _remoteLeaseLive() {
    return this.remoteLease !== null && Date.now() < this.remoteLease.expiresAt
      && performance.now() < this.remoteLeaseDeadline;
  }

  _leaseValue(value, wall) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const lease=Object.fromEntries(LEASE_FIELDS.map(key=>[key,value[key]]));
    if (!['deviceId','bootId','executorEpoch','connectionId','certificateId','leaseId'].every(key=>LEASE_UUID.test(lease[key]))
        || typeof lease.hardwareFingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(lease.hardwareFingerprint)
        || !['leaseEpoch','sequence','issuedAt','expiresAt'].every(key=>Number.isSafeInteger(lease[key]))
        || lease.leaseEpoch < 1 || lease.sequence < 0 || lease.issuedAt > wall + 500
        || lease.expiresAt <= wall || lease.expiresAt - wall > 1000
        || lease.expiresAt <= lease.issuedAt || lease.expiresAt - lease.issuedAt > 1000) return null;
    return Object.freeze(lease);
  }

  _sendRemoteLease(command) {
    if (this.config.remoteLeaseGuard !== true || !this.remoteLeaseWorkerReady || !this.child?.stdin?.writable || this.child.stdin.writableLength > 0) return false;
    const line=JSON.stringify(command)+'\n';
    if (Buffer.byteLength(line)>2048) return false;
    // true means queued to the worker, not acknowledged or physically stopped.
    return this.child.stdin.write(line) !== false;
  }

  armRemoteLease(value) {
    const mono=performance.now(),wall=Date.now(),lease=this._leaseValue(value,wall);
    if (this.config.remoteLeaseGuard !== true || !lease || this._remoteLeaseLive() || lease.leaseEpoch <= this.remoteLeaseEpoch) return false;
    const deadline=mono+Math.min(1000,lease.expiresAt-wall);
    if (performance.now()>=deadline || !this._sendRemoteLease({cmd:'remote_lease_arm',lease})) return false;
    this.remoteLease=lease;this.remoteLeaseEpoch=lease.leaseEpoch;this.remoteLeaseAnchor={mono,wall};this.remoteLeaseDeadline=deadline;
    return true;
  }

  renewRemoteLease(value) {
    const mono=performance.now(),wall=Date.now(),lease=this._leaseValue(value,wall);
    if (!lease || !this._remoteLeaseLive() || !LEASE_BINDING.every(key=>lease[key]===this.remoteLease[key])
        || lease.sequence<=this.remoteLease.sequence) return false;
    const deadline=Math.min(mono+1000,mono+lease.expiresAt-wall,
      this.remoteLeaseAnchor.mono+lease.expiresAt-this.remoteLeaseAnchor.wall);
    if (performance.now()>=deadline || !this._sendRemoteLease({cmd:'remote_lease_renew',lease})) return false;
    this.remoteLease=lease;this.remoteLeaseDeadline=deadline;return true;
  }

  revokeRemoteLease(reason='authorization_revoked') {
    const lease=this.remoteLease;
    this.remoteLease=null;this.remoteLeaseDeadline=null;
    if (!lease || !/^[a-z_]{1,64}$/.test(reason)) return false;
    return this._sendRemoteLease({cmd:'remote_lease_revoke',lease,reason});
  }

  softwareStop(requestId = null) {
    if (!this.child) return false;
    if (this.pendingSoftwareStopId) {
      if (requestId && requestId !== this.pendingSoftwareStopId) this.emit('software_stop_result', {
        request_id: requestId, sdk_released: false, cleanup_state: 'pending',
        stop_state: 'unknown', stop_code: 'STOP_ALREADY_PENDING',
      });
      // The original stop still owns its timer and request correlation. A
      // concurrent caller does not queue another stop or reuse its evidence.
      return true;
    }
    if (!this.connected) return false;
    const child = this.child;
    const id = typeof requestId === 'string' && requestId ? requestId : randomUUID();
    if (!this.send({ cmd: 'software_stop', request_id: id })) return false;
    this.pendingSoftwareStopId = id;

    if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
    this.softwareStopTimer = setTimeout(() => {
      this.softwareStopTimer = null;
      if (this.child !== child || this.pendingSoftwareStopId !== id) return;
      this.pendingSoftwareStopId = null;
      this.emit('software_stop_timeout', {
        request_id: id,
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
    this.pendingSoftwareStopId = null;
    this.revokeRemoteLease('robot_service_shutdown');
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
      remoteLeaseGuard: this.config.remoteLeaseGuard === true,
      remoteLeaseGuardReady: this.remoteLeaseWorkerReady,
      remoteLeaseActive: this._remoteLeaseLive(),
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
    if (message.type === 'bridge_ready') {
      this.ready = true;
      this.remoteLeaseWorkerReady = message.remote_lease_guard === true && message.remote_lease_protocol === 'thirdhand-worker-lease-v1';
    }
    if ((message.type === 'remote_lease_expired' || message.type === 'remote_lease_status' && message.active === false)
        && this.remoteLease && LEASE_BINDING.every(key=>message.binding?.[key]===this.remoteLease[key])) {
      this.remoteLease=null;this.remoteLeaseDeadline=null;
    }
    if (message.type === 'connection') {
      this.connected = Boolean(message.connected);
      if (!message.connected && message.reason === 'software_stop') {
        const matches = !this.pendingSoftwareStopId || message.request_id === this.pendingSoftwareStopId;
        if (matches) {
          if (this.softwareStopTimer) clearTimeout(this.softwareStopTimer);
          this.softwareStopTimer = null;
          this.pendingSoftwareStopId = null;
          // This is an SDK release result, not physical stop evidence.
          this.emit('software_stop_result', message);
        }
      }
    }
    if (message.type === 'error') {
      this.emit('bridge_error', message);
      return;
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
