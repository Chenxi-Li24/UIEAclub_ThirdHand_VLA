'use strict';

const fs = require('node:fs');
const { WebSocket } = require('ws');

const TOKEN_PATTERN = /^[0-9a-f]{64}$/;
const TERMINAL = new Set(['completed', 'failed', 'uncertain', 'interrupted']);

function executionError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function validateLoopback(endpoint) {
  const url = new URL(endpoint);
  if (!['ws:', 'wss:'].includes(url.protocol)
      || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
    throw executionError('execution_endpoint_invalid', 'Execution endpoint must be loopback WebSocket');
  }
  return url.toString();
}

function loadToken(tokenFile) {
  const stat = fs.statSync(tokenFile);
  if (!stat.isFile() || (process.platform !== 'win32' && (stat.mode & 0o077) !== 0)) {
    throw executionError('execution_token_invalid', 'Execution token file permissions are invalid');
  }
  const token = fs.readFileSync(tokenFile, 'utf8').trim();
  if (!TOKEN_PATTERN.test(token)) {
    throw executionError('execution_token_invalid', 'Execution token file content is invalid');
  }
  return token;
}

class ExecutionClient {
  constructor({ endpoint, tokenFile, timeoutMs = 5000 }) {
    this.endpoint = validateLoopback(endpoint);
    this.tokenFile = tokenFile;
    this.timeoutMs = timeoutMs;
    this.socket = null;
    this.connecting = null;
    this.pending = null;
    this.lastError = null;
  }

  publicStatus() {
    return {
      endpoint: this.endpoint,
      connected: this.socket?.readyState === WebSocket.OPEN,
      inFlight: Boolean(this.pending),
      lastError: this.lastError,
    };
  }

  async _connect() {
    if (this.socket?.readyState === WebSocket.OPEN) return this.socket;
    if (this.connecting) return this.connecting;
    this.connecting = new Promise((resolve, reject) => {
      let token;
      try { token = loadToken(this.tokenFile); }
      catch (error) { reject(error); return; }
      const socket = new WebSocket(this.endpoint, {
        headers: { 'x-thirdhand-execution-token': token },
      });
      socket.once('open', () => {
        this.socket = socket;
        this._bind(socket);
        resolve(socket);
      });
      socket.once('error', () => reject(executionError(
        'execution_unavailable', 'Protected execution service unavailable',
      )));
    }).finally(() => { this.connecting = null; });
    return this.connecting;
  }

  _bind(socket) {
    socket.on('message', data => {
      if (data.length > 64 * 1024 || !this.pending) return;
      let message;
      try { message = JSON.parse(data.toString('utf8')); }
      catch { this._uncertain('execution_response_invalid'); return; }
      if (message.type !== 'execution.status') return;
      if (message.primitiveId !== this.pending.primitiveId) {
        this._uncertain('execution_id_mismatch');
        return;
      }
      if (!TERMINAL.has(message.status)) return;
      const pending = this.pending;
      this.pending = null;
      clearTimeout(pending.timer);
      const terminal = Object.freeze({ ...message });
      pending.resolve(terminal);
      pending.stopResolve?.(terminal);
    });
    socket.on('close', () => {
      if (this.socket === socket) this.socket = null;
      if (this.pending) this._rejectPending('execution_connection_closed');
    });
    socket.on('error', () => {
      this.lastError = 'execution_socket_error';
    });
  }

  _sendStop(sessionId) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify({
      schema: 'thirdhand.execution-control.v1', type: 'execution.stop',
      sessionId, reason: 'operator_stop',
    }));
    return true;
  }

  _rejectPending(reason) {
    const pending = this.pending;
    if (!pending) return;
    this.pending = null;
    clearTimeout(pending.timer);
    this.lastError = reason;
    const error = executionError('execution_uncertain', reason);
    pending.reject(error);
    pending.stopReject?.(error);
  }

  _uncertain(reason) {
    if (!this.pending) return;
    this._sendStop(this.pending.sessionId);
    this._rejectPending(reason);
    if (this.socket?.readyState < WebSocket.CLOSING) this.socket.close();
  }

  async execute(primitive) {
    if (this.pending) throw executionError('execution_busy', 'One primitive is already in flight');
    const socket = await this._connect();
    return new Promise((resolve, reject) => {
      const timeout = Math.min(
        Number(primitive?.parameters?.timeoutMs) || this.timeoutMs,
        this.timeoutMs,
      );
      const pending = {
        primitiveId: primitive.primitiveId,
        sessionId: primitive.parameters.sessionId,
        resolve, reject,
        timer: setTimeout(() => this._uncertain('execution_timeout'), timeout),
      };
      this.pending = pending;
      socket.send(JSON.stringify(primitive), error => {
        if (error) this._uncertain('execution_send_failed');
      });
    });
  }

  async stop(sessionId) {
    const socket = await this._connect();
    if (socket.readyState !== WebSocket.OPEN) {
      throw executionError('execution_uncertain', 'Unable to send protected stop');
    }
    if (this.pending?.sessionId === sessionId) {
      return new Promise((resolve, reject) => {
        this.pending.stopResolve = resolve;
        this.pending.stopReject = reject;
        if (!this._sendStop(sessionId)) {
          this.pending.stopResolve = null;
          this.pending.stopReject = null;
          reject(executionError('execution_uncertain', 'Unable to send protected stop'));
        }
      });
    }
    if (!this._sendStop(sessionId)) {
      throw executionError('execution_uncertain', 'Unable to send protected stop');
    }
    return { status: 'stop_requested', sessionId };
  }

  close() {
    if (this.pending) this._uncertain('execution_client_closed');
    if (this.socket?.readyState < WebSocket.CLOSING) this.socket.close();
    this.socket = null;
  }
}

module.exports = { ExecutionClient, loadToken, validateLoopback };
