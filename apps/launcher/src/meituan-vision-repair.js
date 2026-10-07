'use strict';

// A targeted Vision restart, never a CAN/Robot restart or a second camera owner.
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync, spawn } = require('node:child_process');
const { once } = require('node:events');
const { loadRuntimeConfig } = require('./service-config');
const { ServiceSupervisor, probeHttpJson, isAlive, processStartMarker } = require('./service-supervisor');
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

async function repairSharedVision(formalRoot, { force = false } = {}) {
  const config = loadRuntimeConfig(path.join(formalRoot, 'configs/runtime/manual-control.json'),
    { root: formalRoot, nodePath: process.execPath });
  const vision = config.services.find(service => service.id === 'vision' && service.enabled !== false);
  if (!vision) throw new Error('vision_not_configured');
  const host = vision.env.MEITUAN_VISION_HOST || '192.168.58.68';
  const port = Number(vision.env.MEITUAN_VISION_PORT || 1035);
  const probe = pid => probeHttpJson({
    host, port, expect: { serviceId: 'meituan-vision', ...(pid ? { sharedOwnerPid: pid } : {}) }
  });
  const current = await probe();
  if (current.ready && !force) return { action: 'shared-owner-probe' };
  if (!current.ready && current.reason !== 'health_probe_failed:ECONNREFUSED') throw new Error(current.reason);
  const sockets = execFileSync('ss', ['-ltnpH', 'sport = :' + vision.port], { encoding: 'utf8' });
  const owners = [...new Set([...sockets.matchAll(/pid=(\d+)/g)].map(match => Number(match[1])))];
  if (!sockets.trim()) {
    vision.env.MEITUAN_VISION_HOST = host;
    vision.env.MEITUAN_VISION_PORT = String(port);
    const supervisor = new ServiceSupervisor({ runtimeDir: path.join(formalRoot, 'runtime'), services: [vision] });
    const states = await supervisor.ensureAll();
    if (states[0]?.state !== 'ready') throw new Error(states[0]?.reason || 'vision_start_failed');
    if (!(await probe()).ready) throw new Error('meituan_listener_start_failed');
    return { action: 'shared-owner-started', pid: states[0].pid };
  }
  if (owners.length !== 1) throw new Error('vision_owner_ambiguous');
  const pid = owners[0];
  if (pid <= 1 || fs.statSync('/proc/' + pid).uid !== process.getuid()) throw new Error('vision_owner_not_local_user');
  const args = fs.readFileSync('/proc/' + pid + '/cmdline', 'utf8').split('\0').filter(Boolean);
  if (args.length !== 2 || fs.realpathSync(args[0]) !== fs.realpathSync('/proc/' + pid + '/exe')) {
    throw new Error('vision_command_unrecognized');
  }
  const entry = fs.realpathSync(args[1]);
  const deployments = path.resolve(formalRoot, '..', 'deployments');
  const relative = path.relative(deployments, entry);
  if (entry !== path.join(fs.realpathSync(formalRoot), 'services/vision/src/server.js')
      && (relative.startsWith('..' + path.sep) || path.isAbsolute(relative)
        || !/^[^/]+\/tools\/vision\/vision_server_with_state\.js$/.test(relative))) {
    throw new Error('vision_entry_unrecognized');
  }
  const mainHealth = await probeHttpJson({
    host: vision.bind, port: vision.port, expect: { serviceId: 'vision' }
  });
  if (!mainHealth.ready) throw new Error('vision_owner_health_invalid');
  const marker = processStartMarker(pid);
  const cwd = fs.readlinkSync('/proc/' + pid + '/cwd');
  const env = Object.fromEntries(fs.readFileSync('/proc/' + pid + '/environ', 'utf8')
    .split('\0').filter(Boolean).map(value => {
      const index = value.indexOf('=');
      return [value.slice(0, index), value.slice(index + 1)];
    }));
  if (!marker || marker !== processStartMarker(pid)) throw new Error('vision_identity_changed');
  const logs = path.join(formalRoot, 'runtime/logs');
  fs.mkdirSync(logs, { recursive: true });
  const stdout = fs.openSync(path.join(logs, 'meituan-vision-repair.stdout.log'), 'a', 0o600);
  const stderr = fs.openSync(path.join(logs, 'meituan-vision-repair.stderr.log'), 'a', 0o600);
  try {
    if (marker !== processStartMarker(pid)
        || fs.readFileSync('/proc/' + pid + '/cmdline', 'utf8').split('\0').filter(Boolean).join('\0') !== args.join('\0')) {
      throw new Error('vision_identity_changed');
    }
    process.kill(pid, 'SIGTERM');
    for (let attempt = 0; attempt < 200 && isAlive(pid); attempt++) {
      if (marker !== processStartMarker(pid)) break;
      try {
        if (/\)\s+Z\s/.test(fs.readFileSync('/proc/' + pid + '/stat', 'utf8'))) break;
      } catch (error) { if (error.code === 'ENOENT') break; throw error; }
      await pause(100);
    }
    if (marker === processStartMarker(pid) && isAlive(pid)
        && !/\)\s+Z\s/.test(fs.readFileSync('/proc/' + pid + '/stat', 'utf8'))) {
      throw new Error('vision_shutdown_timeout');
    }
    const remaining = execFileSync('ss', ['-ltnpH', 'sport = :' + vision.port], { encoding: 'utf8' });
    if (remaining.trim()) throw new Error('vision_shutdown_incomplete_or_owner_changed');
    const child = spawn(args[0], args.slice(1), {
      cwd, env: { ...env, ...vision.env, MEITUAN_VISION_HOST: host, MEITUAN_VISION_PORT: String(port) },
      detached: true, stdio: ['ignore', stdout, stderr]
    });
    await once(child, 'spawn');
    child.unref();
    for (let attempt = 0; attempt < 120; attempt++) {
      if (!isAlive(child.pid)) throw new Error('vision_restart_exited');
      if ((await probe(child.pid)).ready && (await probeHttpJson({
        host: vision.bind, port: vision.port, expect: { serviceId: 'vision' }
      })).ready) return { action: 'shared-owner-restarted', pid: child.pid };
      await pause(500);
    }
    throw new Error('vision_restart_readiness_timeout');
  } finally {
    fs.closeSync(stdout);
    fs.closeSync(stderr);
  }
}

if (require.main === module) {
  repairSharedVision(process.argv[2]).then(
    result => console.log(JSON.stringify(result)),
    error => { console.log(JSON.stringify({ error: error.message })); process.exitCode = 1; }
  );
}

module.exports = { repairSharedVision };
