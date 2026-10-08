'use strict';

const path = require('node:path');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { loadRuntimeConfig } = require('./service-config');
const { probeHttpJson } = require('./service-supervisor');

const ROOT = path.resolve(__dirname, '../../..');

function ensureProfile(root, profile, quiet) {
  // Delegate to each checkout's existing launcher; never start a second device owner.
  const result = spawnSync('bash', [path.join(root, 'thirdhand'), 'ensure', '--profile', profile],
    { cwd: root, encoding: 'utf8' });
  if (!quiet) {
    if (result.stdout) process.stdout.write(result.stdout);
    if (result.stderr) process.stderr.write(result.stderr);
  }
  return {
    state: !result.error && result.status === 0 ? 'ready' : 'degraded',
    action: 'ensure',
    root,
    reason: result.error ? 'ensure_spawn_' + result.error.code
      : result.status === 0 ? null : 'ensure_exit_' + (result.status ?? result.signal)
  };
}

async function ensureOneClick(options = {}) {
  const formalRoot = options.formalRoot || process.env.THIRDHAND_FORMAL_ROOT || ROOT;
  const meituanRoot = options.meituanRoot || process.env.THIRDHAND_MEITUAN_ROOT
    || formalRoot;
  const config = loadRuntimeConfig(path.join(formalRoot, 'configs/runtime/manual-control.json'),
    { root: formalRoot, nodePath: process.execPath });
  const visionEnv = config.services.find(service => service.id === 'vision')?.env || {};
  const host = visionEnv.MEITUAN_VISION_HOST || '192.168.58.68';
  const port = Number(visionEnv.MEITUAN_VISION_PORT || 1035);
  const services = {
    'manual-control': ensureProfile(formalRoot, 'manual-control', options.quiet),
    'meituan-web': ensureProfile(meituanRoot, 'meituan-web', options.quiet)
  };
  let health = await probeHttpJson({
    host, port, pathName: '/health', expect: { serviceId: 'meituan-vision' }, timeoutMs: 5000
  });
  let repair = null;
  if (health.reason === 'health_probe_failed:ECONNREFUSED') {
    // flock prevents simultaneous shortcuts from restarting the same camera owner twice.
    const run = path.join(formalRoot, 'runtime/run');
    fs.mkdirSync(run, { recursive: true });
    const result = spawnSync('flock', [
      '-n', path.join(run, 'meituan-vision-repair.lock'), process.execPath,
      path.join(__dirname, 'meituan-vision-repair.js'), formalRoot
    ], { encoding: 'utf8' });
    try { repair = JSON.parse(result.stdout); }
    catch { repair = { error: result.error?.code || 'vision_repair_busy_or_failed' }; }
    health = await probeHttpJson({
      host, port, expect: { serviceId: 'meituan-vision' }, timeoutMs: 5000
    });
  }
  services['meituan-vision'] = {
    state: health.ready ? 'ready' : 'degraded',
    action: repair?.action || 'shared-owner-probe',
    bind: host,
    port,
    reason: health.ready ? null : health.reason,
    ...(repair?.error ? { repairReason: repair.error } : {}),
    ...(repair?.pid ? { pid: repair.pid } : {})
  };
  return {
    profile: 'one-click',
    overall: Object.values(services).every(service => service.state === 'ready') ? 'ready' : 'degraded',
    services
  };
}

module.exports = { ensureOneClick };
