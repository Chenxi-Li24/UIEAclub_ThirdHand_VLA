'use strict';

const fs = require('node:fs');
const path = require('node:path');

const CONTENT_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.mtl': 'text/plain; charset=utf-8',
  '.png': 'image/png',
  '.stl': 'model/stl',
  '.urdf': 'application/xml; charset=utf-8',
};

function resolveFile(urlPath, publicDir, assetsDir) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  if (decoded.includes('\0') || decoded.includes('\\')) return null;

  const isModel = decoded === '/models' || decoded.startsWith('/models/');
  const root = path.resolve(isModel ? assetsDir : publicDir);
  let relative = isModel ? decoded.slice('/models'.length) : decoded;
  if (relative === '/' || relative === '') relative = isModel ? '' : '/index.html';

  const candidate = path.resolve(root, `.${relative}`);
  if (candidate !== root && !candidate.startsWith(`${root}${path.sep}`)) return null;
  return candidate;
}

function serveStatic(request, response, config) {
  if (request.method !== 'GET' && request.method !== 'HEAD') return false;
  const pathname = new URL(request.url, 'http://localhost').pathname;
  const filename = resolveFile(pathname, config.publicDir, config.assetsDir);
  if (!filename) {
    response.writeHead(403, { 'content-type': 'application/json; charset=utf-8' });
    response.end(JSON.stringify({ error: 'forbidden' }));
    return true;
  }

  let stat;
  try {
    stat = fs.statSync(filename);
  } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return false;
    throw error;
  }
  if (!stat.isFile()) return false;

  response.writeHead(200, {
    'content-type': CONTENT_TYPES[path.extname(filename).toLowerCase()]
      || 'application/octet-stream',
    'content-length': stat.size,
    'x-content-type-options': 'nosniff',
  });
  if (request.method === 'HEAD') response.end();
  else fs.createReadStream(filename).pipe(response);
  return true;
}

module.exports = { resolveFile, serveStatic };
