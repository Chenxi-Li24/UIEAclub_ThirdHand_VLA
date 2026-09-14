'use strict';

function unavailable(capturedAt) {
  return {
    robot: { reachable: false, connected: false, stateReady: false, moving: false, fresh: false },
    skill: { id: 'manipulation.gripper-control', available: false },
    authorizationReady: false,
    capturedAt,
  };
}

function createReadinessProvider({ robotHealthUrl, fetchImpl = fetch, clock = Date.now }) {
  return async function readiness() {
    const capturedAt = new Date(clock()).toISOString();
    try {
      const response = await fetchImpl(robotHealthUrl);
      if (!response.ok) return unavailable(capturedAt);
      const health = await response.json();
      const robot = health.robot || {};
      const fresh = Number.isFinite(robot.lastStateAt) && clock() - robot.lastStateAt <= 500;
      const snapshot = {
        robot: {
          reachable: true,
          connected: robot.connected === true,
          stateReady: robot.stateReady === true,
          moving: robot.moving === true,
          fresh,
        },
        skill: {
          id: 'manipulation.gripper-control',
          available: health.execution?.available === true,
        },
        authorizationReady: false,
        capturedAt,
      };
      snapshot.authorizationReady = snapshot.robot.connected
        && snapshot.robot.stateReady
        && snapshot.robot.fresh
        && !snapshot.robot.moving
        && snapshot.skill.available;
      return snapshot;
    } catch {
      return unavailable(capturedAt);
    }
  };
}

module.exports = { createReadinessProvider };
