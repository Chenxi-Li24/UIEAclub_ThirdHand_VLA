'use strict';

const DEFAULT_COMMANDS = Object.freeze(new Set([
  'gripper', 'move_joint', 'move_l', 'preset', 'software_stop',
]));

class RobotClient {
  constructor({ transport, allowedCommands = DEFAULT_COMMANDS } = {}) {
    if (typeof transport !== 'function') {
      throw new TypeError('robot transport must be a function');
    }
    this.transport = transport;
    this.allowedCommands = new Set(allowedCommands);
  }

  send(command) {
    if (!command || typeof command !== 'object' || Array.isArray(command) ||
        typeof command.cmd !== 'string' || !this.allowedCommands.has(command.cmd)) {
      return false;
    }
    try {
      return this.transport({ ...command }) === true;
    } catch {
      return false;
    }
  }
}

module.exports = { RobotClient };
