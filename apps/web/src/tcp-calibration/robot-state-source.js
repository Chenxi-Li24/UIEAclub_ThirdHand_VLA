'use strict';

const { randomUUID } = require('node:crypto');

function freeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function poseToMatrix(position, euler) {
  if (!Array.isArray(position) || position.length !== 3 || !position.every(Number.isFinite)
      || !Array.isArray(euler) || euler.length !== 3 || !euler.every(Number.isFinite)) return null;
  const [roll, pitch, yaw] = euler;
  const [cr, sr, cp, sp, cy, sy] = [
    Math.cos(roll), Math.sin(roll), Math.cos(pitch), Math.sin(pitch),
    Math.cos(yaw), Math.sin(yaw),
  ];
  return [
    [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, position[0]],
    [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, position[1]],
    [-sp, cp * sr, cp * cr, position[2]],
    [0, 0, 0, 1],
  ].map(row => row.map(value => value === 0 ? 0 : value));
}

class TcpCalibrationRobotStateSource {
  constructor({ client, requestIdFactory = randomUUID } = {}) {
    if (!client || typeof client.getRobotState !== 'function'
        || typeof client.connect !== 'function' || typeof client.shutdown !== 'function'
        || typeof client.send !== 'function' || typeof client.framePolicyId !== 'string'
        || typeof requestIdFactory !== 'function') {
      throw new TypeError('tcp_calibration_state_source_invalid');
    }
    this.client = client;
    this.requestIdFactory = requestIdFactory;
  }

  connect() { return this.client.connect(); }

  close() { this.client.shutdown(); }

  snapshot() {
    const state = this.client.getRobotState();
    if (!state) return freeze({
      connected: false, locked: true, reason: 'robot_state_unavailable',
      framePolicyId: this.client.framePolicyId,
    });
    const normalization = state.frameNormalization;
    const canonical = state.poseFrame === 'robot_flange'
      && state.framePolicyId === this.client.framePolicyId
      && normalization && (
        normalization.policyId === this.client.framePolicyId
        && normalization.sourcePoseFrame === 'sdk_tool'
        && normalization.destinationPoseFrame === 'robot_flange'
      );
    const matrix = canonical ? poseToMatrix(state.flangePositionM, state.flangeEulerRad) : null;
    if (!matrix) return freeze({
      connected: state.connected === true, locked: true, reason: 'canonical_frame_invalid',
      framePolicyId: this.client.framePolicyId,
    });
    return freeze({
      connected: state.connected === true,
      healthy: state.healthy === true,
      stationary: state.stationary === true,
      stateFresh: state.stateFresh === true,
      locked: !(state.connected === true && state.healthy === true
        && state.stationary === true && state.stateFresh === true),
      reason: null,
      poseFrame: 'robot_flange',
      framePolicyId: this.client.framePolicyId,
      stateSequence: state.stateSequence,
      producerMonotonicNs: state.producerMonotonicNs,
      TBaseFlange: matrix,
      sdkToolPose: state.sdkToolPose,
    });
  }

  softwareStop() {
    const requestId = this.requestIdFactory();
    if (typeof requestId !== 'string' || !requestId) return false;
    return this.client.send({ cmd: 'software_stop', request_id: requestId });
  }
}

module.exports = { TcpCalibrationRobotStateSource };
