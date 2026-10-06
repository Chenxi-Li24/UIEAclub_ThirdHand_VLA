'use strict';
// UI fixture only: no child process, SDK, microphone, camera or robot connection.
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');
const { serveStatic } = require('../../../../apps/web/src/static-server');
const root = path.resolve(__dirname, '../../../..');
let phase = 'stopped';
let keywords = true;
const calls = { start: 0, stop: 0, frames: 0 };
const jpeg = process.env.DUMMY_FIXTURE_JPEG ? fs.readFileSync(process.env.DUMMY_FIXTURE_JPEG).toString('base64') : null;
const server = http.createServer((req, res) => {
  const route = new URL(req.url, 'http://localhost').pathname;
  function json(value) { res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(value)); }
  if (route === '/api/dummy/status') return json({ available: true, backendReady: true,
    phase, running: phase === 'running', owned: phase === 'running', keywordsEnabled: keywords,
    robot: { connected: true, stateReady: true, moving: false },
    limits: { j1MaxSpeedDegS: 50, j4MaxSpeedDegS: 50 },
    observation: phase === 'running' ? { mode: 'FOLLOWING', status: 'locked',
      receive_age_ms: 40, robot_joints_deg: [10,0,0,5,0,0] } : null });
  if (route === '/api/dummy/frame') { calls.frames++; return json({ state: { frame_id: calls.frames, status: 'locked' }, jpeg_base64: jpeg }); }
  if (route === '/fixture/calls') return json(calls);
  if (route === '/api/dummy/start' && req.method === 'POST') {
    let body = '';
    req.on('data', b => { body += b; });
    req.on('end', () => { const value = JSON.parse(body); keywords = value.keywords; calls.start++; phase = 'running'; json({ phase }); });
    return;
  }
  if (route === '/api/dummy/stop' && req.method === 'POST') { calls.stop++; phase = 'stopped'; return json({ phase }); }
  if (route.startsWith('/models/')) { res.writeHead(404); res.end(); return; }
  // Keep all unrelated live modules disconnected in this fixture.
  if (route.startsWith('/api/') || route.startsWith('/camera/')) { res.writeHead(503); res.end('{}'); return; }
  if (!serveStatic(req, res, { publicDir: path.join(root, 'apps/web/public'), assetsDir: path.join(root, 'assets/robot') })) {
    res.writeHead(404); res.end();
  }
});
server.listen(Number(process.env.DUMMY_FIXTURE_PORT || 19984), '127.0.0.1', () => console.log('Dummy UI fixture: http://127.0.0.1:19984 (simulation only)'));
process.on('SIGINT', () => server.close(() => process.exit(0)));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
