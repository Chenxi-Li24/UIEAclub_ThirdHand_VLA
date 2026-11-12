'use strict';
const net = require('node:net');
const os = require('node:os');
const { execFile } = require('node:child_process');
const { promisify } = require('node:util');
const run = promisify(execFile);
const result = (id, status, detail) => ({ id, status, detail, checkedAt: new Date().toISOString() });
function probe(url) {
  return new Promise(resolve => {
    let socket;
    try {
      const target = new URL(url);
      socket = net.createConnection({ host: target.hostname, port: Number(target.port || (target.protocol === 'https:' || target.protocol === 'wss:' ? 443 : 80)) });
      const finish = ok => { socket.destroy(); resolve(ok); };
      socket.setTimeout(3000, () => finish(false));
      socket.once('connect', () => finish(true)); socket.once('error', () => finish(false));
    } catch { socket?.destroy(); resolve(false); }
  });
}
function createSystemDiagnostics({ getRobotState = () => ({}), voiceUrl, visionUrl, connect = probe, interfaces = os.networkInterfaces, execute = run, platform = process.platform, clock = () => performance.now() } = {}) {
  return async function check(id) {
    try {
      if (id === 'sdk') {
        const state = getRobotState();
        return result(id, state.connected && state.stateFresh ? 'passed' : 'failed', !state.connected ? 'SDK disconnected. Check the robot service and CAN connection.' : !state.stateFresh ? 'SDK feedback is stale. Check the robot service.' : 'SDK connected with fresh robot feedback.');
      }
      if (id === 'ai' || id === 'vision') {
        const started = clock();
        const ok = await connect(id === 'ai' ? voiceUrl : visionUrl);
        const latencyMs = Math.max(0, Math.round((clock() - started) * 10) / 10);
        return { ...result(id, ok ? 'passed' : 'failed', ok ? 'Service port reachable. Model inference is not tested.' : 'Service unavailable or timed out. Check the host service.'),
          latencyMs: ok ? latencyMs : null, latencyKind: 'host-tcp-connect' };
      }
      if (id === 'network') {
        const active = Object.values(interfaces()).some(entries => entries?.some(address => !address.internal));
        return result(id, active ? 'passed' : 'failed', active ? 'Host has an assigned network address. Internet reachability is not tested.' : 'No external host network address detected.');
      }
      if (id === 'wifi') {
        if (platform !== 'linux') return result(id, 'unknown', 'Host Wi-Fi inspection is available on Ubuntu only.');
        const { stdout } = await execute('nmcli', ['-t', '-f', 'TYPE,STATE', 'device', 'status'], { timeout: 3000, maxBuffer: 16384, env: { ...process.env, LC_ALL: 'C' } });
        const wifi = stdout.trim().split('\n').filter(line => line.startsWith('wifi:'));
        return result(id, !wifi.length ? 'skipped' : wifi.some(line => line === 'wifi:connected') ? 'passed' : 'warning', !wifi.length ? 'No Wi-Fi adapter found. Ethernet or Tailscale may be in use.' : wifi.some(line => line === 'wifi:connected') ? 'Ubuntu Wi-Fi is connected.' : 'Ubuntu Wi-Fi is disconnected. Another network may still be available.');
      }
      return result(id, 'unknown', 'Unknown check.');
    } catch { return result(id, 'unknown', 'Unable to inspect this check on the host.'); }
  };
}
module.exports = { createSystemDiagnostics };
