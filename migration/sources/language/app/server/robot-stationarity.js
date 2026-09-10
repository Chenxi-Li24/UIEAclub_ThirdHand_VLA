'use strict';

class RobotStationarityTracker {
  constructor({
    windowMs = 250,
    minSamples = 3,
    maxJointDriftDeg = 0.15,
    maxReportedVelocityDegS = 2.0,
  } = {}) {
    if (!Number.isFinite(windowMs) || windowMs <= 0) throw new Error('windowMs must be positive');
    if (!Number.isInteger(minSamples) || minSamples < 2) throw new Error('minSamples must be at least two');
    if (!Number.isFinite(maxJointDriftDeg) || maxJointDriftDeg <= 0) {
      throw new Error('maxJointDriftDeg must be positive');
    }
    if (!Number.isFinite(maxReportedVelocityDegS) || maxReportedVelocityDegS <= 0) {
      throw new Error('maxReportedVelocityDegS must be positive');
    }
    this.windowMs = windowMs;
    this.minSamples = minSamples;
    this.maxJointDriftDeg = maxJointDriftDeg;
    this.maxReportedVelocityDegS = maxReportedVelocityDegS;
    this.samples = [];
  }

  reset() {
    this.samples = [];
  }

  update({ jointsDeg, velocitiesDegS, robotState, motionActive, observedAtMs = Date.now() }) {
    const validJoints = Array.isArray(jointsDeg) && jointsDeg.length === 6
      && jointsDeg.every(Number.isFinite);
    const validVelocities = Array.isArray(velocitiesDegS) && velocitiesDegS.length === 6
      && velocitiesDegS.every(Number.isFinite);
    if (!validJoints || !validVelocities || !Number.isFinite(observedAtMs)) {
      this.reset();
      return false;
    }
    if (motionActive === true || robotState === 'MOVING') {
      this.reset();
      return false;
    }
    if (velocitiesDegS.some(value => Math.abs(value) > this.maxReportedVelocityDegS)) {
      this.reset();
      return false;
    }

    this.samples.push({ atMs: observedAtMs, jointsDeg: [...jointsDeg] });
    const cutoff = observedAtMs - this.windowMs;
    this.samples = this.samples.filter(sample => sample.atMs >= cutoff);
    if (this.samples.length < this.minSamples) return false;

    for (let joint = 0; joint < 6; joint += 1) {
      const values = this.samples.map(sample => sample.jointsDeg[joint]);
      if (Math.max(...values) - Math.min(...values) > this.maxJointDriftDeg) return false;
    }
    return true;
  }
}

module.exports = { RobotStationarityTracker };
