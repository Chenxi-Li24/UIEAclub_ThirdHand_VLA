const fs = require('node:fs');
const path = require('node:path');

function readState(statePath) {
  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf8'));
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { schemaVersion: 1, authorizationState: 'revoked', services: [] };
    }
    throw error;
  }
}

function writeStateAtomic(statePath, state) {
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  const temporary = `${statePath}.${process.pid}.tmp`;
  const fd = fs.openSync(temporary, 'w', 0o600);
  try {
    fs.writeFileSync(fd, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(temporary, statePath);
}

function removeState(statePath) {
  try {
    fs.unlinkSync(statePath);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

module.exports = { readState, writeStateAtomic, removeState };
