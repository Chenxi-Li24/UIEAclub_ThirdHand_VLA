'use strict';

function loadAsrV2RuntimePolicy(env = process.env) {
  return {
    localRobotBridgeEnabled: env.LOCAL_ROBOT_BRIDGE_ENABLED === '1',
    localCameraBridgeEnabled: env.LOCAL_CAMERA_BRIDGE_ENABLED === '1',
  };
}

function startLocalBridges(policy, bridges) {
  const result = { robotStarted: false, cameraStarted: false };
  if (policy.localRobotBridgeEnabled && bridges.robot) {
    bridges.robot.start();
    result.robotStarted = true;
  }
  if (policy.localCameraBridgeEnabled && bridges.camera) {
    bridges.camera.start();
    result.cameraStarted = true;
  }
  return result;
}

module.exports = { loadAsrV2RuntimePolicy, startLocalBridges };
