'use strict';

const { spawn } = require('child_process');
const path = require('path');

class LumosHttpService {
  constructor(config = {}) {
    this.config = config;
    this.child = null;
    this.stopping = false;
    this.restartTimer = null;
  }

  get streamUrl() { return `http://${this.config.host}:${this.config.port}/camera_lumos`; }
  get snapshotUrl() { return `http://${this.config.host}:${this.config.port}/frame.jpg`; }

  start() {
    if (this.config.managed !== true || this.child) return false;
    this.stopping = false;
    const script = path.join(__dirname, 'lumos_http_server.py');
    const child = spawn(this.config.python, ['-u', script], {
      cwd: __dirname,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        LUMOS_HTTP_HOST: this.config.host,
        LUMOS_HTTP_PORT: String(this.config.port),
        LUMOS_OUTPUT_SIZE: String(this.config.outputSize),
        LUMOS_FPS: String(this.config.fps),
      },
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    this.child = child;
    child.stderr.on('data', data => {
      const message = data.toString('utf8').trim();
      if (message) console.warn(`[Lumos] ${message}`);
    });
    child.on('error', error => console.error(`[Lumos] service failed: ${error.message}`));
    child.on('exit', code => {
      if (this.child !== child) return;
      this.child = null;
      if (!this.stopping) {
        console.warn(`[Lumos] service exited (${code}); retrying`);
        this.restartTimer = setTimeout(() => { this.restartTimer = null; this.start(); }, 2000);
        this.restartTimer.unref();
      }
    });
    return true;
  }

  shutdown() {
    this.stopping = true;
    if (this.restartTimer) clearTimeout(this.restartTimer);
    this.restartTimer = null;
    if (this.child) this.child.kill('SIGTERM');
  }
}

module.exports = { LumosHttpService };
