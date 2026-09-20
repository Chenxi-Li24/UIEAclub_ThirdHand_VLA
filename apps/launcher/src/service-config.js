const fs = require('node:fs');
const path = require('node:path');

const LOOPBACK_ONLY_PORTS = new Set([3000, 3004, 3100]);

function loadRuntimeConfig(configPath, options = {}) {
  const root = options.root || path.resolve(configPath, '..', '..', '..');
  const nodePath = options.nodePath || process.execPath;
  const expand = value => typeof value === 'string'
    ? value
      .replaceAll('${NODE}', nodePath)
      .replaceAll('${ROOT}', root)
    : value;
  const document = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  if (!Array.isArray(document.services)) throw new Error('services must be an array');

  let can = null;
  if (document.can) {
    const interfaceName = document.can.interface;
    if (typeof interfaceName !== 'string' || !/^[A-Za-z0-9_.:-]+$/.test(interfaceName)) {
      throw new Error('can.interface is invalid');
    }
    if (!Number.isInteger(document.can.bitrate) || document.can.bitrate <= 0) {
      throw new Error('can.bitrate must be a positive integer');
    }
    if (!Number.isInteger(document.can.restartMs) || document.can.restartMs < 0) {
      throw new Error('can.restartMs must be a non-negative integer');
    }
    can = {
      enabled: document.can.enabled !== false,
      interface: interfaceName,
      bitrate: document.can.bitrate,
      restartMs: document.can.restartMs,
    };
  }

  const seen = new Set();
  const services = document.services.map(raw => {
    if (!raw.id || seen.has(raw.id)) throw new Error(`duplicate or missing service id: ${raw.id}`);
    seen.add(raw.id);
    if (!Array.isArray(raw.args)) throw new Error(`service ${raw.id} args must be an array`);
    if (!Number.isInteger(raw.port) || raw.port < 1 || raw.port > 65535) {
      throw new Error(`service ${raw.id} has invalid port`);
    }
    const bind = raw.bind || '127.0.0.1';
    if (LOOPBACK_ONLY_PORTS.has(raw.port) && bind !== '127.0.0.1' && !raw.allowLan) {
      throw new Error(`service ${raw.id} must bind to loopback`);
    }
    const command = expand(raw.command);
    if (!path.isAbsolute(command)) throw new Error(`service ${raw.id} command must be absolute`);
    return {
      ...raw,
      command,
      args: raw.args.map(expand),
      cwd: expand(raw.cwd || '${ROOT}'),
      env: Object.fromEntries(
        Object.entries(raw.env || {}).map(([name, value]) => [name, expand(value)]),
      ),
      bind,
    };
  });
  return { profile: document.profile, description: document.description, can, services };
}

function loadServiceConfig(configPath, options = {}) {
  return loadRuntimeConfig(configPath, options).services;
}

module.exports = { loadRuntimeConfig, loadServiceConfig };
