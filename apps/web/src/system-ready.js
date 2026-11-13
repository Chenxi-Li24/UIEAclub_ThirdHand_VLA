'use strict';
const path = require('node:path');
const { loadRuntimeConfig } = require('../../launcher/src/service-config');
const { ServiceSupervisor, probeConfiguredService } = require('../../launcher/src/service-supervisor');
const { CanInterfaceManager, needsFullProfileRecovery } = require('../../launcher/src/can-interface');

// Keep the serving gateway alive. Full CAN recovery belongs to the host launcher.
async function prepareSystem({ root = path.resolve(__dirname, '../../..'), load = loadRuntimeConfig,
  Supervisor = ServiceSupervisor, Can = CanInterfaceManager, probe = probeConfiguredService } = {}) {
  const config = load(path.join(root, 'configs/runtime/manual-control.json'), { root, nodePath: process.execPath });
  const services = config.services.filter(service => service.id !== 'web');
  const canManager = new Can({ interfaceName: config.can.interface, bitrate: config.can.bitrate, restartMs: config.can.restartMs });
  const before = await canManager.inspect();
  const robot = services.find(service => service.id === 'robot' && service.enabled);
  const robotProbe = robot ? await probe(robot) : { ready: false };
  if (needsFullProfileRecovery(before, { robotServiceReady: robotProbe.ready })) {
    return { overall: 'degraded', reason: 'host_recovery_required', services: {}, can: before };
  }
  const can = await canManager.ensure();
  if (can.state !== 'ready') return { overall: 'degraded', can, services: {} };
  const supervisor = new Supervisor({ runtimeDir: path.join(root, 'runtime'), services });
  const statuses = await supervisor.ensureAll();
  return { overall: statuses.length && statuses.every(s => s.state === 'ready') ? 'ready' : 'degraded',
    can, services: Object.fromEntries(statuses.map(s => [s.id, s])), profile: 'manual-control' };
}

function createSystemReady({ prepare = prepareSystem, platform = process.platform, busy = () => false } = {}) {
  let pending = null;
  let state = { overall: 'unchecked', services: {} };
  return async function handle(req, res, pathname) {
    if (pathname !== '/api/system-ready') return false;
    const reply = (code, body) => { res.writeHead(code, { 'content-type': 'application/json', 'cache-control': 'no-store' }); res.end(JSON.stringify(body)); return true; };
    const local = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    let host; try { host = new URL('http://' + req.headers.host).hostname; } catch {}
    const allowed = local && ['localhost', '127.0.0.1', '[::1]'].includes(host) && platform === 'linux';
    if (req.method === 'GET') return reply(200, { ...state, available: allowed, pending: Boolean(pending), reason: allowed ? state.reason : 'local_ubuntu_required' });
    if (req.method !== 'POST') return reply(405, { error: 'method_not_allowed' });
    let sameOrigin = false;
    try { const origin = new URL(req.headers.origin); sameOrigin = origin.host === req.headers.host && ['http:', 'https:'].includes(origin.protocol); } catch {}
    if (!allowed || !sameOrigin || req.headers['sec-fetch-site'] === 'cross-site' || req.headers['x-thirdhand-action'] !== 'prepare') return reply(403, { error: 'local_origin_required' });
    if (busy()) return reply(409, { error: 'robot_control_busy' });
    if (pending) return reply(409, { error: 'preparation_in_progress' });
    state = { overall: 'preparing', services: {} };
    pending = Promise.resolve().then(prepare).then(result => { state = result; }, () => { state = { overall: 'failed', reason: 'preparation_failed', services: {} }; }).finally(() => { pending = null; });
    return reply(202, state);
  };
}
module.exports = { prepareSystem, createSystemReady };
