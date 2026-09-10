const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { readState, writeStateAtomic } = require('./state-store');

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

class ServiceSupervisor {
  constructor({ runtimeDir, services, onEvent = () => {}, startTimeoutMs = 5000, stopTimeoutMs = 5000 }) {
    this.runtimeDir = path.resolve(runtimeDir);
    this.statePath = path.join(this.runtimeDir, 'run', 'state.json');
    this.services = services;
    this.onEvent = onEvent;
    this.startTimeoutMs = startTimeoutMs;
    this.stopTimeoutMs = stopTimeoutMs;
    this.children = new Map();
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

  async _waitReady(child, readyFile) {
    const deadline = Date.now() + this.startTimeoutMs;
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
    const state = readState(this.statePath);
    const records = new Map(state.services.map(record => [record.id, record]));

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
      try {
        await this._waitReady(child, readyFile);
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
    return this.status();
  }

  async status() {
    const state = readState(this.statePath);
    const records = new Map(state.services.map(record => [record.id, record]));
    return this.services.filter(item => item.enabled).map(service => {
      const record = records.get(service.id);
      return {
        id: service.id,
        pid: record?.pid || null,
        state: this._owned(record, service) ? 'ready' : (record?.status === 'stopped' ? 'stopped' : 'unavailable'),
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
    return this.status();
  }
}

module.exports = { ServiceSupervisor, commandHash, isAlive, processStartMarker };
