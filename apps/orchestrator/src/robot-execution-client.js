'use strict';

const fs = require('node:fs');
const { WebSocket } = require('ws');

class RobotExecutionClient {
  constructor({ url, token, tokenFile, WebSocketImpl = WebSocket }) {
    this.url = url;
    this.token = token || (tokenFile ? fs.readFileSync(tokenFile, 'utf8').trim() : null);
    this.WebSocketImpl = WebSocketImpl;
    this.sockets = new Set();
    this.pending = new Map();
  }

  execute(primitive, { signal } = {}) {
    if (!this.token) return Promise.reject(Object.assign(new Error('Robot execution token unavailable'), { code: 'execution_token_unavailable' }));
    if (signal?.aborted) return Promise.reject(Object.assign(new Error('Robot execution interrupted'), { code: 'interrupted' }));
    return new Promise((resolve, reject) => {
      let settled = false;
      const socket = new this.WebSocketImpl(this.url, {
        headers: { 'x-thirdhand-execution-token': this.token },
      });
      this.sockets.add(socket);
      let timer;
      const finish = (error, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener('abort', abort);
        this.sockets.delete(socket);
        this.pending.delete(socket);
        if (socket.readyState < this.WebSocketImpl.CLOSING) socket.close();
        if (error) reject(error);
        else resolve(value);
      };
      const abort = () => finish(Object.assign(new Error('Robot execution interrupted'), { code: 'interrupted' }));
      this.pending.set(socket, finish);
      timer = setTimeout(() => finish(Object.assign(new Error('Robot execution response timeout'), { code: 'feedback_timeout' })), primitive.parameters.timeoutMs + 1000);
      signal?.addEventListener('abort', abort, { once: true });
      socket.once('open', () => socket.send(JSON.stringify(primitive)));
      socket.on('message', data => {
        let message;
        try { message = JSON.parse(data.toString('utf8')); } catch { return; }
        if (message.primitiveId !== primitive.primitiveId || message.type !== 'execution.status') return;
        if (['completed', 'failed', 'uncertain', 'interrupted'].includes(message.status)) finish(null, message);
      });
      socket.once('error', error => finish(error));
      socket.once('close', () => {
        if (this.sockets.has(socket)) finish(Object.assign(new Error('Robot execution connection closed'), { code: 'robot_connection_closed' }));
      });
    });
  }

  close() {
    const error = Object.assign(new Error('Robot execution client closed'), { code: 'client_closed' });
    for (const finish of [...this.pending.values()]) finish(error);
    for (const socket of this.sockets) socket.terminate();
    this.sockets.clear();
    this.pending.clear();
  }
}

module.exports = { RobotExecutionClient };
