'use strict';

const { WebSocket } = require('ws');

const DEFAULT_MAX_QUEUED_BYTES = 1024 * 1024;

class WebSocketProxy {
  constructor(upstreamUrl, options = {}) {
    this.upstreamUrl = upstreamUrl;
    this.subprotocol = options.subprotocol;
    this.maxQueuedBytes = options.maxQueuedBytes ?? DEFAULT_MAX_QUEUED_BYTES;
    this.sessions = new Set();
  }

  attach(browser) {
    const upstream = new WebSocket(
      this.upstreamUrl,
      this.subprotocol ? [this.subprotocol] : undefined,
    );
    const session = {
      browser,
      upstream,
      queue: [],
      queuedBytes: 0,
      closed: false,
    };
    this.sessions.add(session);

    const finish = () => {
      if (session.closed) return;
      session.closed = true;
      session.queue.length = 0;
      session.queuedBytes = 0;
      this.sessions.delete(session);
    };

    upstream.on('open', () => {
      for (const { data, isBinary } of session.queue.splice(0)) {
        if (upstream.readyState !== WebSocket.OPEN) break;
        upstream.send(data, { binary: isBinary });
      }
      session.queuedBytes = 0;
    });
    upstream.on('message', (data, isBinary) => {
      if (browser.readyState === WebSocket.OPEN) {
        browser.send(data, { binary: isBinary });
      }
    });
    upstream.on('error', () => {
      if (browser.readyState === WebSocket.OPEN) {
        browser.close(1011, 'upstream unavailable');
      }
    });
    upstream.on('close', (code, reason) => {
      if (browser.readyState === WebSocket.OPEN) {
        const downstreamCode = code === 1000 ? 1000 : 1011;
        browser.close(downstreamCode, reason.toString().slice(0, 123));
      }
      finish();
    });

    browser.on('message', (data, isBinary) => {
      if (upstream.readyState === WebSocket.OPEN) {
        upstream.send(data, { binary: isBinary });
        return;
      }
      if (upstream.readyState !== WebSocket.CONNECTING) return;

      const size = Buffer.byteLength(data);
      if (session.queuedBytes + size > this.maxQueuedBytes) {
        browser.close(1009, 'queued messages exceed limit');
        upstream.terminate();
        finish();
        return;
      }
      session.queue.push({ data: Buffer.from(data), isBinary });
      session.queuedBytes += size;
    });
    browser.on('close', (code, reason) => {
      if (upstream.readyState < WebSocket.CLOSING) {
        upstream.close(code === 1000 ? 1000 : 1001, reason.toString().slice(0, 123));
      }
      finish();
    });
    browser.on('error', () => {
      if (upstream.readyState < WebSocket.CLOSING) upstream.terminate();
      finish();
    });
  }

  close() {
    for (const { browser, upstream } of this.sessions) {
      browser.terminate();
      upstream.terminate();
    }
    this.sessions.clear();
  }
}

module.exports = {
  DEFAULT_MAX_QUEUED_BYTES,
  WebSocketProxy,
};
