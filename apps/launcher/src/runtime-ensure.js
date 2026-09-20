const { needsFullProfileRecovery } = require('./can-interface');

async function ensureRuntime({ canManager, serviceSupervisor, services, probeService }) {
  const initialCan = await canManager.inspect();
  const robot = services.find(service => service.enabled && service.id === 'robot');
  const robotProbe = robot ? await probeService(robot) : { ready: false };
  const fullProfile = needsFullProfileRecovery(initialCan, {
    robotServiceReady: Boolean(robotProbe.ready),
  });

  let stopStatuses = [];
  let can;
  if (fullProfile) {
    stopStatuses = await serviceSupervisor.stopAll();
    const incomplete = stopStatuses.filter(item => item.state !== 'stopped');
    if (incomplete.length > 0) {
      can = {
        state: 'failed', action: 'blocked', interface: initialCan.interface,
        reason: 'profile_stop_incomplete',
        detail: incomplete.map(item => `${item.id}:${item.state}`).join(','),
      };
    } else {
      can = await canManager.ensure({ force: true });
    }
  } else {
    can = await canManager.ensure();
  }

  const serviceStatuses = await serviceSupervisor.ensureAll();
  return {
    can,
    services: serviceStatuses,
    recoveryMode: fullProfile ? 'full-profile' : (initialCan.ready ? 'none' : 'can-only'),
    stopStatuses,
  };
}

module.exports = { ensureRuntime };
