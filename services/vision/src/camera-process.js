'use strict';

const { EventEmitter } = require('node:events');
const { spawn } = require('node:child_process');
const readline = require('node:readline');

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
}

class CameraProcess extends EventEmitter {
  constructor(config) {
    super();
    this.config = config;
    this.child = null;
    this.closing = false;
    this._status = {
      camera: { status: 'stopped', sequence: null, error: null },
      inference: { status: 'stopped', error: null },
      selection: { stableId: null },
    };
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
    this._status.camera = {
      status: 'starting',
      sequence: null,
      error: null,
    };
    this._status.inference = { status: 'loading', error: null };
    const child = spawn(
      this.config.python,
      [
        '-u',
        this.config.bridgeScript,
        '--config',
        this.config.visionConfig,
        '--executable',
        this.config.xvisioExecutable,
      ],
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
        },
        stdio: ['pipe', 'ignore', 'pipe', 'pipe', 'pipe', 'pipe', 'pipe'],
      },
    );
    this.child = child;
    child.stdio[4].on('data', chunk => this.streams.raw.push(chunk));
    child.stdio[5].on('data', chunk => this.streams.vision.push(chunk));
    child.stdio[6].on('data', chunk => this.streams.depth.push(chunk));
    const events = readline.createInterface({ input: child.stdio[3] });
    events.on('line', line => this._handleEvent(line));
    child.stderr.on('data', chunk => {
      const message = chunk.toString('utf8').trim();
      if (message) this.emit('log', { level: 'warning', message });
    });
    child.on('error', error => this._setProcessError(error));
    child.on('exit', (code, signal) => {
      if (this.child !== child) return;
      this.child = null;
      if (!this.closing) {
        this._setProcessError(
          new Error(`camera bridge exited: ${signal || code}`),
        );
      }
    });
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
    if (message.type === 'runtime_status') {
      this._status = {
        camera: { ...message.camera },
        inference: { ...message.inference },
        selection: { ...message.selection },
      };
    } else if (message.type === 'detection_result') {
      this.lastDetection = message;
    }
    this.emit('event', message);
  }

  _setProcessError(error) {
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
    };
  }

  subscribe(kind, response) {
    return this.streams[kind]?.subscribe(response) || false;
  }

  unsubscribe(kind, response) {
    return this.streams[kind]?.unsubscribe(response) || false;
  }

  send(message) {
    if (!this.child?.stdin?.writable || this.child.stdin.destroyed) return false;
    const allowed = new Set(['select_target', 'release_target', 'shutdown']);
    if (!allowed.has(message?.type)) return false;
    if (message.type === 'select_target' &&
        (!Number.isSafeInteger(message.stableId) ||
         message.stableId < 1 || message.stableId > 5)) {
      return false;
    }
    return this.child.stdin.write(`${JSON.stringify(message)}\n`);
  }

  async close() {
    this.closing = true;
    for (const stream of Object.values(this.streams)) stream.close();
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

module.exports = { CameraProcess, LatestMjpegBroadcaster };
