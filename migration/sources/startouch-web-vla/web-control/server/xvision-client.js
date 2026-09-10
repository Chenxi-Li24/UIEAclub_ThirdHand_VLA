'use strict';

const { EventEmitter } = require('events');
const http = require('http');
const https = require('https');
const { WebSocket } = require('ws');

const STREAM_PATHS = new Set([
  '/camera_lumos',
  '/camera_lumos_vision',
]);

const EVENT_TYPES = new Set([
  'bridge_ready',
  'camera_status',
  'detection_result',
  'selection_status',
  'vision_error',
  'vision_status',
]);

function parseUrl(value, protocols, label) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new TypeError(`${label} must be a valid URL`);
  }
  if (!protocols.has(parsed.protocol)) {
    throw new TypeError(`${label} uses an unsupported protocol`);
  }
  return parsed;
}

function normalizeSelection({ side, ordinal, requestId }) {
  if (!['left', 'right'].includes(side)) {
    throw new TypeError('invalid selection side');
  }
  if (!Number.isInteger(ordinal) || ordinal < 1 || ordinal > 32) {
    throw new TypeError('invalid selection ordinal');
  }
  if (typeof requestId !== 'string' || requestId.length < 1 || requestId.length > 128) {
    throw new TypeError('invalid selection request id');
  }
  return {
    cmd: 'select_bottle',
    side,
    ordinal,
    request_id: requestId,
  };
}

class XVisionClient extends EventEmitter {
  constructor({
    baseUrl,
    wsUrl,
    reconnectMs = 2000,
    requestTimeoutMs = 2000,
  }) {
    super();
    this.baseUrl = parseUrl(baseUrl, new Set(['http:', 'https:']), 'XVisio base URL');
    this.wsUrl = parseUrl(wsUrl, new Set(['ws:', 'wss:']), 'XVisio WebSocket URL');
    if (!Number.isFinite(reconnectMs) || reconnectMs < 10 || reconnectMs > 60_000) {
      throw new TypeError('reconnectMs must be within [10, 60000]');
    }
    if (!Number.isFinite(requestTimeoutMs) || requestTimeoutMs < 100 || requestTimeoutMs > 30_000) {
      throw new TypeError('requestTimeoutMs must be within [100, 30000]');
    }
    this.reconnectMs = reconnectMs;
    this.requestTimeoutMs = requestTimeoutMs;
    this.socket = null;
    this.connected = false;
    this.stopping = true;
    this.reconnectTimer = null;
  }

  start() {
    if (this.socket || this.reconnectTimer) return;
    this.stopping = false;
    this._connect();
  }

  stop() {
    this.stopping = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.socket;
    this.socket = null;
    this.connected = false;
    if (socket) socket.terminate();
  }

  selectBottle(selection) {
    const command = normalizeSelection(selection);
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(command));
    return true;
  }

  proxyMjpeg(upstreamPath, request, response) {
    if (!STREAM_PATHS.has(upstreamPath)) {
      throw new TypeError(`Unsupported XVisio stream path: ${upstreamPath}`);
    }
    const target = new URL(upstreamPath, this.baseUrl);
    const transport = target.protocol === 'https:' ? https : http;
    const upstream = transport.get(target, upstreamResponse => {
      if (!upstreamResponse.statusCode || upstreamResponse.statusCode < 200 ||
          upstreamResponse.statusCode >= 300) {
        upstreamResponse.resume();
        if (!response.headersSent) {
          response.statusCode = 503;
          response.end('XVisio stream unavailable');
        } else {
          response.destroy();
        }
        return;
      }
      response.statusCode = 200;
      response.setHeader(
        'Content-Type',
        upstreamResponse.headers['content-type'] ||
          'multipart/x-mixed-replace; boundary=frame'
      );
      response.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
      if (typeof response.flushHeaders === 'function') response.flushHeaders();
      upstreamResponse.pipe(response);
    });
    upstream.setTimeout(this.requestTimeoutMs, () => {
      upstream.destroy(new Error('XVisio stream request timed out'));
    });
    upstream.on('error', error => {
      if (!response.headersSent) {
        response.statusCode = 503;
        response.end(`XVisio stream unavailable: ${error.message}`);
      } else {
        response.destroy(error);
      }
    });
    const closeUpstream = () => upstream.destroy();
    if (request && typeof request.once === 'function') request.once('close', closeUpstream);
    if (response && typeof response.once === 'function') response.once('close', closeUpstream);
    return upstream;
  }

  _connect() {
    if (this.stopping || this.socket) return;
    const socket = new WebSocket(this.wsUrl.href);
    this.socket = socket;
    socket.on('open', () => {
      if (this.socket !== socket) return;
      this.connected = true;
      this.emit('connection', { connected: true });
    });
    socket.on('message', payload => {
      let message;
      try {
        message = JSON.parse(payload.toString());
      } catch {
        this.emit('log', { level: 'warning', message: 'Invalid XVisio JSON event' });
        return;
      }
      if (!message || typeof message !== 'object' || !EVENT_TYPES.has(message.type)) return;
      this.emit(message.type, message);
      this.emit('message', message);
    });
    socket.on('error', error => {
      this.emit('log', { level: 'warning', message: `XVisio WebSocket: ${error.message}` });
    });
    socket.on('close', () => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.connected = false;
      this.emit('connection', { connected: false });
      this._scheduleReconnect();
    });
  }

  _scheduleReconnect() {
    if (this.stopping || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._connect();
    }, this.reconnectMs);
  }
}

module.exports = {
  EVENT_TYPES,
  STREAM_PATHS,
  XVisionClient,
  normalizeSelection,
};
