'use strict';

const { JOINT_AXES, JOINT_ORIGINS_M } = require('../language/startouch-forward-kinematics');

function multiply(first, second) {
  return first.map(row => second[0].map((unused, column) =>
    row.reduce((sum, value, index) => sum + value * second[index][column], 0)));
}

function rotate(rotation, vector) {
  return rotation.map(row => row.reduce((sum, value, index) => sum + value*vector[index], 0));
}

function axisAngle(axis, angle) {
  const [x, y, z] = axis;
  const cosine = Math.cos(angle);
  const sine = Math.sin(angle);
  const complement = 1 - cosine;
  return [
    [cosine+x*x*complement, x*y*complement-z*sine, x*z*complement+y*sine],
    [y*x*complement+z*sine, cosine+y*y*complement, y*z*complement-x*sine],
    [z*x*complement-y*sine, z*y*complement+x*sine, cosine+z*z*complement],
  ];
}

function forwardKinematicsFlangePose(jointsDeg) {
  if (!Array.isArray(jointsDeg) || jointsDeg.length !== 6 || !jointsDeg.every(Number.isFinite)) {
    throw new TypeError('forward kinematics requires six finite joint angles');
  }
  let rotation = [[1,0,0],[0,1,0],[0,0,1]];
  const positionM = [0,0,0];
  for (let index = 0; index < 6; index += 1) {
    const shift = rotate(rotation, JOINT_ORIGINS_M[index]);
    shift.forEach((value, coordinate) => { positionM[coordinate] += value; });
    rotation = multiply(rotation, axisAngle(JOINT_AXES[index], jointsDeg[index]*Math.PI/180));
  }
  return { positionM, rotation };
}

module.exports = { forwardKinematicsFlangePose };
