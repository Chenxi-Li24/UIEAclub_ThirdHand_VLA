'use strict';

const express = require('express');
const http = require('http');

const MAX_JPEG_BYTES = 16 * 1024 * 1024;
const SNAPSHOT_TIMEOUT_MS = 3000;

function requireLoopbackUrl(value, name) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 4096) {
    throw new TypeError(`${name} must be a bounded URL`);
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new TypeError(`${name} must be a URL`);
  }
  if (
    parsed.protocol !== 'http:'
    || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || parsed.username !== ''
    || parsed.password !== ''
  ) {
    throw new TypeError(`${name} must be a loopback HTTP URL`);
  }
  return value;
}

function fetchFirstJpeg(url, options = {}) {
  const timeoutMs = options.timeoutMs || SNAPSHOT_TIMEOUT_MS;
  const maxBytes = options.maxBytes || MAX_JPEG_BYTES;
  return new Promise((resolve, reject) => {
    let settled = false;
    let buffer = Buffer.alloc(0);
    const request = http.get(url, { headers: { 'cache-control': 'no-cache' } }, response => {
      if (response.statusCode !== 200) {
        response.resume();
        settled = true;
        reject(new Error(`snapshot upstream returned ${response.statusCode}`));
        return;
      }
      response.on('data', chunk => {
        if (settled) return;
        buffer = Buffer.concat([buffer, chunk]);
        if (buffer.length > maxBytes) {
          settled = true;
          response.destroy();
          reject(new Error('snapshot exceeds maximum JPEG size'));
          return;
        }
        const start = buffer.indexOf(Buffer.from([0xff, 0xd8]));
        const end = start >= 0
          ? buffer.indexOf(Buffer.from([0xff, 0xd9]), start + 2)
          : -1;
        if (start < 0 || end < 0) return;
        const jpeg = Buffer.from(buffer.subarray(start, end + 2));
        settled = true;
        resolve(jpeg);
        response.destroy();
      });
      response.once('end', () => {
        if (settled) return;
        settled = true;
        reject(new Error('snapshot upstream ended without a complete JPEG'));
      });
      response.once('error', error => {
        if (settled) return;
        settled = true;
        reject(error);
      });
    });
    request.setTimeout(timeoutMs, () => {
      if (settled) return;
      settled = true;
      request.destroy();
      reject(new Error('snapshot upstream timed out'));
    });
    request.once('error', error => {
      if (settled) return;
      settled = true;
      reject(error);
    });
  });
}

class CalibrationPreviewService {
  constructor(options = {}) {
    this.urls = Object.freeze({
      lumos: requireLoopbackUrl(options.lumosUrl, 'lumosUrl'),
      d435: requireLoopbackUrl(options.d435Url, 'd435Url'),
    });
    this.fetchJpeg = options.fetchJpeg || fetchFirstJpeg;
    if (typeof this.fetchJpeg !== 'function') throw new TypeError('fetchJpeg must be a function');
  }

  snapshot(camera) {
    if (!Object.hasOwn(this.urls, camera)) {
      return Promise.reject(new TypeError('camera must be lumos or d435'));
    }
    return this.fetchJpeg(this.urls[camera]);
  }
}

function requestIsLoopback(request) {
  const address = request.socket?.remoteAddress;
  return address === '127.0.0.1' || address === '::1' || address === '::ffff:127.0.0.1';
}

function createCalibrationPreviewRouter({ service, isLoopback = requestIsLoopback } = {}) {
  if (!(service instanceof CalibrationPreviewService)) {
    throw new TypeError('service must be a CalibrationPreviewService');
  }
  if (typeof isLoopback !== 'function') throw new TypeError('isLoopback must be a function');
  const router = express.Router();
  router.get('/:camera.jpg', async (request, response) => {
    response.setHeader('Cache-Control', 'no-store');
    if (!isLoopback(request)) {
      response.status(403).send('local access required');
      return;
    }
    try {
      const jpeg = await service.snapshot(request.params.camera);
      response.type('image/jpeg').send(jpeg);
    } catch {
      response.status(503).send('camera preview unavailable');
    }
  });
  return router;
}

module.exports = {
  CalibrationPreviewService,
  createCalibrationPreviewRouter,
  fetchFirstJpeg,
};
