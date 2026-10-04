'use strict';

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

class PrototypeSimulator {
  #commands = [];
  constructor({ onCommand = () => {} } = {}) {
    if (typeof onCommand !== 'function') throw new TypeError('prototype_callback_invalid');
    this.onCommand = onCommand;
  }
  get commands() { return Object.freeze([...this.#commands]); }
  send(command) {
    const copy = freeze(structuredClone(command));
    this.#commands.push(copy);
    this.onCommand(copy);
    return true;
  }
}

module.exports = { PrototypeSimulator };
