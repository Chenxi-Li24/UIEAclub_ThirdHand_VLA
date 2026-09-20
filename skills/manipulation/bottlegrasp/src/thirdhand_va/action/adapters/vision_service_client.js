'use strict';

const http = require('node:http');
const { EventEmitter } = require('node:events');

const STREAM_PATHS = Object.freeze({
  overlay: '/camera/xvisio/vision',
  raw: '/camera/xvisio/raw',
  depth: '/camera/xvisio/depth',
});

class VisionServiceClient extends EventEmitter {
  constructor({
    WebSocketImpl,
    wsUrl = 'ws://127.0.0.1:3100/ws',
    httpUrl = 'http://127.0.0.1:3100',
    maxReadyAgeMs = 2000,
    reconnectDelayMs = 1000,
  } = {}) {
    super();
    if (typeof WebSocketImpl !== 'function') {
      throw new TypeError('VisionServiceClient requires WebSocketImpl');
    }
    this.WebSocketImpl = WebSocketImpl;
    this.wsUrl = wsUrl;
    this.httpUrl = httpUrl.replace(/\/+$/, '');
    this.maxReadyAgeMs = maxReadyAgeMs;
    this.reconnectDelayMs = Math.max(10, Number(reconnectDelayMs) || 1000);
    this.ws = null;
    this.reconnectTimer = null;
    this.stopped = true;
    this.connected = false;
    this.cameraReady = false;
    this.inferenceReady = false;
    this.lastProcessedAtMs = 0;
    this.runtimeEvidence = null;
    this.streamRequests = new Map();
  }

  start() {
    if (this.ws || this.reconnectTimer) return false;
    this.stopped = false;
    const socket = new this.WebSocketImpl(this.wsUrl);
    this.ws = socket;
    socket.on('open', () => {
      this.connected = true;
      this.emit('camera_status', { ready: false, source: 'vision-service' });
    });
    socket.on('message', raw => this._onMessage(raw));
    socket.on('error', error => {
      this.emit('bridge_error', { message: `Vision Service: ${error.message}` });
    });
    socket.on('close', () => {
      if (this.ws !== socket) return;
      this.ws = null;
      this.connected = false;
      this.cameraReady = false;
      this.inferenceReady = false;
      this.lastProcessedAtMs = 0;
      this.emit('camera_status', { ready: false, source: 'vision-service' });
      this._scheduleReconnect();
    });
    return true;
  }

  _scheduleReconnect() {
    if (this.stopped || this.ws || this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.stopped && !this.ws) this.start();
    }, this.reconnectDelayMs);
    this.reconnectTimer.unref?.();
  }

  send(message) {
    if (!message || typeof message !== 'object' || !this.ws ||
        this.ws.readyState !== this.WebSocketImpl.OPEN) return false;
    let outbound;
    if (message.type === 'select_bottle') {
      outbound = {
        type: 'select_target',
        stableId: message.stable_id,
        requestId: message.request_id,
      };
    } else if (message.type === 'release_bottle') {
      outbound = {
        type: 'release_target',
        requestId: message.request_id,
      };
    } else if (['arm_state', 'reset_target_pose_reference'].includes(message.type)) {
      outbound = { ...message };
    } else {
      return false;
    }
    try {
      this.ws.send(JSON.stringify(outbound));
      return true;
    } catch {
      return false;
    }
  }

  sendArmState(
    flangePosition, flangeEuler, jointsDeg, velocitiesDegS,
    stationary, observedAtNs,
  ) {
    return this.send({
      type: 'arm_state',
      pose_frame: 'robot_flange',
      flange_position_m: flangePosition,
      flange_euler_rad: flangeEuler,
      joints_deg: jointsDeg,
      velocities_deg_s: velocitiesDegS,
      stationary,
      observed_monotonic_ns: observedAtNs,
    });
  }

  getInfo() {
    const fresh = this.lastProcessedAtMs > 0 &&
      Date.now() - this.lastProcessedAtMs <= this.maxReadyAgeMs;
    return {
      ready: this.connected && this.cameraReady && this.inferenceReady && fresh,
      streaming: this.connected && this.cameraReady,
      source: 'vision-service',
      runtimeEvidence: this.runtimeEvidence ? { ...this.runtimeEvidence } : null,
      calibrationApproved:
        this.runtimeEvidence?.calibration_approved === true,
    };
  }

  subscribeMjpeg(kind, response) {
    const streamPath = STREAM_PATHS[kind];
    if (!streamPath || !response || this.streamRequests.has(response)) return false;
    const request = http.get(`${this.httpUrl}${streamPath}`, upstream => {
      if (upstream.statusCode !== 200) {
        upstream.resume();
        response.end();
        return;
      }
      upstream.on('data', chunk => {
        if (!response.destroyed && !response.writableEnded) response.write(chunk);
      });
      upstream.once('end', () => {
        this.streamRequests.delete(response);
        if (!response.destroyed) response.end();
      });
    });
    request.once('error', () => {
      this.streamRequests.delete(response);
      if (!response.destroyed) response.end();
    });
    this.streamRequests.set(response, request);
    return true;
  }

  unsubscribeMjpeg(_kind, response) {
    const request = this.streamRequests.get(response);
    if (!request) return false;
    this.streamRequests.delete(response);
    request.destroy();
    return true;
  }

  shutdown() {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    for (const request of this.streamRequests.values()) request.destroy();
    this.streamRequests.clear();
    const socket = this.ws;
    this.ws = null;
    this.connected = false;
    this.cameraReady = false;
    this.inferenceReady = false;
    this.lastProcessedAtMs = 0;
    if (socket) {
      try { socket.close(); } catch {}
    }
  }

  _onMessage(raw) {
    let message;
    try {
      message = JSON.parse(raw.toString());
    } catch {
      this.emit('bridge_error', { message: 'Vision Service returned invalid JSON' });
      return;
    }
    if (message.type === 'runtime_status') {
      this.cameraReady = message.camera?.status === 'ready';
      this.inferenceReady = message.inference?.status === 'ready';
      if (message.runtimeEvidence) {
        this.runtimeEvidence = Object.freeze({ ...message.runtimeEvidence });
      }
      if (this.cameraReady && this.inferenceReady) this.lastProcessedAtMs = Date.now();
    } else if (message.type === 'bridge_ready') {
      this.runtimeEvidence = Object.freeze({
        camera_serial: message.camera_serial,
        registration_id: message.registration_id,
        camera_mount_id: message.camera_mount_id,
        vision_config_id: message.vision_config_id,
        calibration_id: message.calibration_id,
        calibration_approved: message.calibration_approved === true,
        model_provenance: message.model_provenance,
      });
    } else if (message.type === 'detection_result') {
      this.lastProcessedAtMs = Date.now();
    }
    this.emit(message.type, message);
    this.emit('message', message);
  }
}

module.exports = { STREAM_PATHS, VisionServiceClient };
