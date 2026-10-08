'use strict';

const { WebSocketProxy } = require('./websocket-proxy');

class VisionProxy extends WebSocketProxy {
  constructor(upstreamUrl) {
    super(upstreamUrl, { maxQueuedBytes: 16 * 1024 });
  }
}

module.exports = { VisionProxy };
