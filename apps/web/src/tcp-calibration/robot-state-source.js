'use strict';

const { randomUUID } = require('node:crypto');
const { CalibrationPoseStability } = require('./pose-stability');

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
  constructor({ client, requestIdFactory = randomUUID, confirmPoseStability = false } = {}) {
    if (!client || typeof client.getRobotState !== 'function'
        || typeof client.connect !== 'function' || typeof client.shutdown !== 'function'
        || typeof client.send !== 'function' || typeof client.framePolicyId !== 'string'
        || typeof requestIdFactory !== 'function') {
      throw new TypeError('tcp_calibration_state_source_invalid');
    }
    this.client = client;
    this.requestIdFactory = requestIdFactory;
    if(confirmPoseStability) {
      if(typeof client.on!=='function')throw new TypeError('calibration_feedback_subscription_required');
      this.poseStability=new CalibrationPoseStability();
      client.on('robot_state',state=>this.poseStability.observe(state));
      client.on('connection',()=>this.poseStability.reset());
      client.on('protocol',()=>this.poseStability.reset());
      client.on('error',()=>this.poseStability.reset());
    }
  }

  connect() {
    // Reconnect only the read-only transport. Never enable hardware or enter
    // teach mode as a consequence of a service restart.
    if (!this.reconnectTimer) {
      this.reconnectTimer = setInterval(() => {
        if (this.client.ws === null) this.client.connect();
      }, 1000);
      this.reconnectTimer.unref?.();
    }
    return this.client.connect();
  }

  close() { clearInterval(this.reconnectTimer); this.reconnectTimer = null; this.client.shutdown(); }

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
    const stationary=this.poseStability ? this.poseStability.ready(state) : state.stationary===true;
    const reason=!state.connected?'robot_disconnected':!state.healthy?'robot_unhealthy'
      :!state.stateFresh?'robot_feedback_stale':state.teachActive?'robot_teaching'
      :this.teachTransition?'teach_transition_pending':!stationary?'pose_not_stable':null;
    return freeze({
      connected: state.connected === true,
      healthy: state.healthy === true,
      stationary,
      stabilityMode: this.poseStability ? 'pose_window_1s' : 'joint_velocity',
      stateFresh: state.stateFresh === true,
      teachActive: state.teachActive === true,
      teachSupported: state.teachSupported === true,
      locked: !(state.connected === true && state.healthy === true
        && stationary && state.stateFresh === true && state.teachActive !== true
        && !this.teachTransition),
      reason,
      streamId: state.streamId,
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

  async teach(command) {
    if (!['teach_start', 'teach_hold', 'teach_keepalive'].includes(command)
        || typeof this.client.sendTeachCommand !== 'function') return false;
    const requestId = this.requestIdFactory();
    if (typeof requestId !== 'string' || !requestId) return false;
    if(command==='teach_start'&&this.snapshot().locked)throw new Error('robot_state_locked');
    const transition=command!=='teach_keepalive';
    if(transition&&this.teachTransition)throw new Error('teach_transition_pending');
    if(transition)this.teachTransition=true;
    if(transition)this.poseStability?.reset();
    try{
      const result=await this.client.sendTeachCommand({ cmd: command, request_id: requestId });
      return result?.accepted===true;
    }finally{if(transition)this.teachTransition=false;}
  }
}

module.exports = { TcpCalibrationRobotStateSource };
