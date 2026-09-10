const fs = require('node:fs');
const path = require('node:path');

const LOOPBACK_ONLY_PORTS = new Set([3000, 3004, 3100]);

function loadServiceConfig(configPath, options = {}) {
  const root = options.root || path.resolve(configPath, '..', '..', '..');
  const nodePath = options.nodePath || process.execPath;
  const document = JSON.parse(fs.readFileSync(configPath, 'utf8'));
  if (!Array.isArray(document.services)) throw new Error('services must be an array');

  const seen = new Set();
  return document.services.map(raw => {
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
    const command = raw.command.replace('${NODE}', nodePath).replace('${ROOT}', root);
    if (!path.isAbsolute(command)) throw new Error(`service ${raw.id} command must be absolute`);
    return {
      ...raw,
      command,
      args: raw.args.map(value => value.replace('${ROOT}', root)),
      cwd: (raw.cwd || '${ROOT}').replace('${ROOT}', root),
      bind,
    };
  });
}

module.exports = { loadServiceConfig };
