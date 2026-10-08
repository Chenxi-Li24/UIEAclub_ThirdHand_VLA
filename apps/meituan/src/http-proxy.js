'use strict';

const http = require('node:http');
const https = require('node:https');

const RESPONSE_HEADERS = new Set([
  'cache-control',
  'content-length',
  'content-type',
]);

function writeUnavailable(response, error) {
  if (response.headersSent) {
    response.destroy(error);
    return;
  }
  const body = JSON.stringify({
    code: 'vision_upstream_unavailable',
    service: 'vision',
    msg: `Vision Service unavailable: ${error.message}`,
  });
  response.writeHead(503, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function proxyHttpRequest(request, response, baseUrl, upstreamPath) {
  const target = new URL(upstreamPath, baseUrl);
  const transport = target.protocol === 'https:' ? https : http;
  const headers = {};
  for (const name of ['accept', 'content-type', 'content-length']) {
    if (request.headers[name] !== undefined) headers[name] = request.headers[name];
  }

  const upstream = transport.request({
    protocol: target.protocol,
    hostname: target.hostname,
    port: target.port,
    method: request.method,
    path: `${target.pathname}${target.search}`,
    headers,
  });

  upstream.on('response', incoming => {
    const outgoingHeaders = {};
    for (const [name, value] of Object.entries(incoming.headers)) {
      if (RESPONSE_HEADERS.has(name) && value !== undefined) {
        outgoingHeaders[name] = value;
      }
    }
    response.writeHead(incoming.statusCode || 502, outgoingHeaders);
    incoming.on('error', error => response.destroy(error));
    incoming.pipe(response);
    response.on('close', () => {
      if (!incoming.complete) incoming.destroy();
    });
  });
  upstream.on('error', error => writeUnavailable(response, error));
  request.on('aborted', () => upstream.destroy());
  request.pipe(upstream);
}

module.exports = { proxyHttpRequest };
