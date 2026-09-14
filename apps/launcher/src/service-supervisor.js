const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { readState, writeStateAtomic } = require('./state-store');
const {
  executionTokenPath,
  prepareExecutionToken,
  removeExecutionToken,
} = require('./runtime-secrets');

function isAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function processStartMarker(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    const fields = stat.slice(stat.lastIndexOf(')') + 2).trim().split(/\s+/);
    return fields[19] || null;
  } catch {
    return null;
  }
}

function commandHash(service) {
  return crypto.createHash('sha256').update(JSON.stringify({
    command: service.command,
    args: service.args || [],
    cwd: service.cwd || process.cwd(),
  })).digest('hex');
}

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

function probeTcpPort({ host, port, timeoutMs = 250 }) {
  return new Promise(resolve => {
    const socket = net.createConnection({ host, port });
    let settled = false;
    const finish = result => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeoutMs, () => finish({ occupied: false, errorCode: 'ETIMEDOUT' }));
    socket.once('connect', () => finish({ occupied: true, errorCode: null }));
    socket.once('error', error => {
      if (error.code === 'ECONNREFUSED') {
        finish({ occupied: false, errorCode: null });
        return;
      }
      finish({ occupied: false, errorCode: error.code || 'PORT_PROBE_FAILED' });
    });
  });
}

function probeHost(bind) {
  if (!bind || bind === '0.0.0.0') return '127.0.0.1';
  if (bind === '::') return '::1';
  return bind;
}

class ServiceSupervisor {
  constructor({ runtimeDir, services, onEvent = () => {}, startTimeoutMs = 5000, stopTimeoutMs = 5000 }) {
    this.runtimeDir = path.resolve(runtimeDir);
    this.statePath = path.join(this.runtimeDir, 'run', 'state.json');
    this.services = services;
    this.onEvent = onEvent;
    this.startTimeoutMs = startTimeoutMs;
    this.stopTimeoutMs = stopTimeoutMs;
    this.children = new Map();
    const expectedTokenPath = executionTokenPath(this.runtimeDir);
    const configuredTokenPaths = services
      .map(service => service.env?.ROBOT_EXECUTION_TOKEN_FILE)
      .filter(Boolean)
      .map(value => path.resolve(value));
    if (configuredTokenPaths.some(value => value !== expectedTokenPath)) {
      throw new Error(`launcher may only manage execution token at ${expectedTokenPath}`);
    }
    this.managesExecutionToken = configuredTokenPaths.length > 0;
  }

  _owned(record, service) {
    return Boolean(
      record
      && record.status === 'ready'
      && record.commandHash === commandHash(service)
      && isAlive(record.pid)
      && processStartMarker(record.pid) === record.processStartMarker
    );
  }

  async preflight() {
    const state = readState(this.statePath);
    const records = new Map(state.services.map(record => [record.id, record]));
    const services = [];

    for (const service of this.services.filter(item => item.enabled)) {
      const record = records.get(service.id);
      const base = {
        id: service.id,
        bind: service.bind || '127.0.0.1',
        port: Number.isInteger(service.port) ? service.port : null,
      };
      if (this._owned(record, service)) {
        services.push({ ...base, state: 'owned_running', reason: null });
        continue;
      }
      if (record?.status === 'ready' && isAlive(record.pid)) {
        services.push({ ...base, state: 'blocked_external', reason: 'process_identity_mismatch' });
        continue;
      }
      if (!Number.isInteger(service.port)) {
        services.push({ ...base, state: 'available', reason: null });
        continue;
      }
      const probe = await probeTcpPort({ host: probeHost(service.bind), port: service.port });
      if (probe.errorCode) {
        services.push({ ...base, state: 'blocked_external', reason: `port_probe_failed:${probe.errorCode}` });
      } else if (probe.occupied) {
        services.push({ ...base, state: 'blocked_external', reason: 'external_port_in_use' });
      } else {
        services.push({ ...base, state: 'available', reason: null });
      }
    }

    return {
      ok: services.every(service => service.state !== 'blocked_external'),
      services,
    };
  }

  async _waitReady(child, readyFile, timeoutMs = this.startTimeoutMs) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) throw new Error(`service exited with code ${child.exitCode}`);
      if (fs.existsSync(readyFile)) return;
      await delay(25);
    }
    throw new Error('service readiness timeout');
  }

  async _terminateStartedChild(child) {
    if (!isAlive(child.pid)) return;
    child.kill('SIGTERM');
    await Promise.race([once(child, 'exit'), delay(this.stopTimeoutMs)]);
    if (isAlive(child.pid)) {
      child.kill('SIGKILL');
      await Promise.race([once(child, 'exit'), delay(this.stopTimeoutMs)]);
    }
  }

  async startAll() {
    fs.mkdirSync(path.join(this.runtimeDir, 'run'), { recursive: true });
    fs.mkdirSync(path.join(this.runtimeDir, 'logs'), { recursive: true });
    const preflight = await this.preflight();
    if (!preflight.ok) {
      const state = readState(this.statePath);
      const records = new Map(state.services.map(record => [record.id, record]));
      for (const blocked of preflight.services.filter(item => item.state === 'blocked_external')) {
        const previous = records.get(blocked.id) || { id: blocked.id };
        records.set(blocked.id, {
          ...previous,
          status: 'not_owned',
          lastError: blocked.reason,
        });
      }
      writeStateAtomic(this.statePath, { ...state, services: [...records.values()] });
      const error = new Error('one or more service ports are owned by external processes');
      error.code = 'external_service_ownership';
      error.services = preflight.services
        .filter(item => item.state === 'blocked_external')
        .map(({ id, bind, port, reason }) => ({ id, bind, port, reason }));
      throw error;
    }
    const secret = this.managesExecutionToken
      ? prepareExecutionToken({ runtimeDir: this.runtimeDir })
      : null;
    const state = readState(this.statePath);
    const records = new Map(state.services.map(record => [record.id, record]));
    const startedThisRun = [];

    try {
      for (const service of this.services.filter(item => item.enabled)) {
        const existing = records.get(service.id);
        if (this._owned(existing, service)) continue;

        const readyFile = path.join(this.runtimeDir, 'run', `${service.id}.ready`);
        try { fs.unlinkSync(readyFile); } catch (error) { if (error.code !== 'ENOENT') throw error; }
        const stdoutFd = fs.openSync(path.join(this.runtimeDir, 'logs', `${service.id}.stdout.log`), 'a');
        const stderrFd = fs.openSync(path.join(this.runtimeDir, 'logs', `${service.id}.stderr.log`), 'a');
        const child = spawn(service.command, service.args || [], {
          cwd: service.cwd || process.cwd(),
          env: { ...process.env, ...(service.env || {}), THIRDHAND_SERVICE_ID: service.id, THIRDHAND_READY_FILE: readyFile },
          detached: true,
          stdio: ['ignore', stdoutFd, stderrFd],
        });
        fs.closeSync(stdoutFd);
        fs.closeSync(stderrFd);
        this.children.set(service.id, child);
        startedThisRun.push({ service, child, readyFile });
        try {
          await this._waitReady(child, readyFile, service.startTimeoutMs);
        } catch (error) {
          await this._terminateStartedChild(child);
          try { fs.unlinkSync(readyFile); } catch (unlinkError) {
            if (unlinkError.code !== 'ENOENT') throw unlinkError;
          }
          throw error;
        }
        child.unref();

        const record = {
          id: service.id,
          pid: child.pid,
          processStartMarker: processStartMarker(child.pid),
          commandHash: commandHash(service),
          status: 'ready',
          startedAt: new Date().toISOString(),
          lastError: null,
        };
        records.set(service.id, record);
        this.onEvent({ type: 'started', serviceId: service.id, pid: child.pid });
        writeStateAtomic(this.statePath, { ...state, schemaVersion: 1, services: [...records.values()] });
      }
    } catch (error) {
      for (const { service, child, readyFile } of [...startedThisRun].reverse()) {
        await this._terminateStartedChild(child);
        try { fs.unlinkSync(readyFile); } catch (unlinkError) {
          if (unlinkError.code !== 'ENOENT') throw unlinkError;
        }
        const record = records.get(service.id);
        if (record) {
          record.status = 'stopped';
          record.lastError = 'group_start_failed';
        }
      }
      writeStateAtomic(this.statePath, { ...state, schemaVersion: 1, services: [...records.values()] });
      if (secret?.created) removeExecutionToken({ runtimeDir: this.runtimeDir });
      throw error;
    }
    return this.status();
  }

  async status() {
    const state = readState(this.statePath);
    const records = new Map(state.services.map(record => [record.id, record]));
    return this.services.filter(item => item.enabled).map(service => {
      const record = records.get(service.id);
      const owned = this._owned(record, service);
      return {
        id: service.id,
        pid: record?.pid || null,
        state: owned ? 'ready' : (
          ['stopped', 'not_owned', 'stop_timeout'].includes(record?.status)
            ? record.status
            : 'unavailable'
        ),
        reason: owned ? null : (record?.lastError || null),
        bind: service.bind || '127.0.0.1',
        port: Number.isInteger(service.port) ? service.port : null,
      };
    });
  }

  async stopAll() {
    const state = readState(this.statePath);
    state.authorizationState = 'revoked';
    writeStateAtomic(this.statePath, state);
    const records = new Map(state.services.map(record => [record.id, record]));
    const ordered = this.services.filter(item => item.enabled).sort((a, b) => b.shutdownOrder - a.shutdownOrder);

    for (const service of ordered) {
      const record = records.get(service.id);
      if (!record || record.status === 'stopped') continue;
      if (!this._owned(record, service)) {
        record.status = 'not_owned';
        record.lastError = 'process_identity_mismatch';
        writeStateAtomic(this.statePath, state);
        continue;
      }
      process.kill(record.pid, service.gracefulSignal || 'SIGTERM');
      const deadline = Date.now() + this.stopTimeoutMs;
      while (isAlive(record.pid) && Date.now() < deadline) await delay(25);
      if (isAlive(record.pid)) {
        record.status = 'stop_timeout';
        record.lastError = 'graceful_stop_timeout';
      } else {
        record.status = 'stopped';
        record.lastError = null;
        this.onEvent({ type: 'stopped', serviceId: service.id, pid: record.pid });
      }
      writeStateAtomic(this.statePath, state);
    }
    writeStateAtomic(this.statePath, state);
    const cleanStop = this.services
      .filter(item => item.enabled)
      .every(service => records.get(service.id)?.status === 'stopped');
    if (cleanStop && this.managesExecutionToken) {
      removeExecutionToken({ runtimeDir: this.runtimeDir });
    }
    return this.status();
  }
}

module.exports = {
  ServiceSupervisor,
  commandHash,
  isAlive,
  probeTcpPort,
  processStartMarker,
};
