const { spawnSync } = require('node:child_process');

function packetCount(text, direction) {
  const pattern = new RegExp(
    `${direction}:\\s+bytes\\s+packets[^\\n]*\\n\\s*\\d+\\s+(\\d+)`,
    'm',
  );
  const match = text.match(pattern);
  return match ? Number(match[1]) : null;
}

function parseCanLinkDetails(text, expected) {
  const interfaceName = expected.interfaceName;
  const escapedName = interfaceName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const flags = text.match(new RegExp(`^\\d+:\\s+${escapedName}:\\s+<([^>]*)>`, 'm'));
  const state = text.match(/can state\s+([A-Z-]+)/);
  const bitrate = text.match(/\bbitrate\s+(\d+)/);
  const restartMs = text.match(/\brestart-ms\s+(\d+)/);
  const parsed = {
    interface: interfaceName,
    exists: Boolean(flags),
    up: Boolean(flags && flags[1].split(',').includes('UP')),
    state: state ? state[1] : null,
    bitrate: bitrate ? Number(bitrate[1]) : null,
    restartMs: restartMs ? Number(restartMs[1]) : 0,
    rxPackets: packetCount(text, 'RX'),
    txPackets: packetCount(text, 'TX'),
  };
  parsed.ready = Boolean(
    parsed.exists
    && parsed.up
    && parsed.bitrate === expected.bitrate
    && parsed.restartMs === expected.restartMs
  );
  return parsed;
}

function needsFullProfileRecovery(canState, { robotServiceReady = false } = {}) {
  if (!canState?.exists) return false;
  const oneWayTraffic = Number(canState.txPackets) > 0 && Number(canState.rxPackets) === 0;
  return oneWayTraffic || (!canState.ready && robotServiceReady);
}

class CanInterfaceManager {
  constructor({ interfaceName = 'can0', bitrate = 1000000, restartMs = 100, run } = {}) {
    this.interfaceName = interfaceName;
    this.bitrate = bitrate;
    this.restartMs = restartMs;
    this.run = run || ((command, args) => spawnSync(command, args, { encoding: 'utf8' }));
  }

  _status(state, action, extra = {}) {
    return {
      state: 'ready',
      action,
      interface: this.interfaceName,
      bitrate: state.bitrate,
      restartMs: state.restartMs,
      rxPackets: state.rxPackets,
      txPackets: state.txPackets,
      ...extra,
    };
  }

  async inspect() {
    const result = this.run('ip', [
      '-details', '-statistics', 'link', 'show', this.interfaceName,
    ]);
    if (result.error || result.status !== 0) {
      return {
        interface: this.interfaceName,
        exists: false,
        up: false,
        state: null,
        bitrate: null,
        restartMs: null,
        rxPackets: null,
        txPackets: null,
        ready: false,
        error: result.error?.message || String(result.stderr || '').trim(),
      };
    }
    return parseCanLinkDetails(result.stdout || '', {
      interfaceName: this.interfaceName,
      bitrate: this.bitrate,
      restartMs: this.restartMs,
    });
  }

  async ensure({ force = false } = {}) {
    const before = await this.inspect();
    if (!before.exists) {
      return {
        state: 'failed', action: 'blocked', interface: this.interfaceName,
        reason: 'can_interface_missing', detail: before.error || null,
      };
    }
    if (before.ready && !force) return this._status(before, 'kept');

    const commands = [
      ['sudo', ['-n', 'ip', 'link', 'set', this.interfaceName, 'down']],
      ['sudo', [
        '-n', 'ip', 'link', 'set', this.interfaceName, 'type', 'can',
        'bitrate', String(this.bitrate), 'restart-ms', String(this.restartMs),
      ]],
      ['sudo', ['-n', 'ip', 'link', 'set', this.interfaceName, 'up']],
    ];
    for (const [command, args] of commands) {
      const result = this.run(command, args);
      if (result.error || result.status !== 0) {
        return {
          state: 'failed', action: 'reconfigure_failed', interface: this.interfaceName,
          reason: 'can_reconfigure_failed',
          detail: result.error?.message || String(result.stderr || '').trim() || `${command} exited ${result.status}`,
        };
      }
    }

    const after = await this.inspect();
    if (!after.ready) {
      return {
        state: 'failed', action: 'verification_failed', interface: this.interfaceName,
        reason: 'can_verification_failed', detail: after.error || null,
      };
    }
    return this._status(after, force ? 'full_recovery' : 'reconfigured');
  }
}

module.exports = {
  CanInterfaceManager,
  needsFullProfileRecovery,
  parseCanLinkDetails,
};
