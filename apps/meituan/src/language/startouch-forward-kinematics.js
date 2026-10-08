'use strict';

// Six revolute-joint origins and axes copied from the checked-in FastTouchV3 URDF.
// All six URDF origin RPY values are zero. The tool offset matches ArmModel's
// gripper/camera preview anchor in web/js/main.js.
const JOINT_ORIGINS_M = Object.freeze([
  [0, 0, 0],
  [0.024, 0, 0.117],
  [-0.265, 0, 0],
  [0.265, 0, 0.062],
  [0.078, 0, -0.00295],
  [0.0255, 0, 0],
]);
const JOINT_AXES = Object.freeze([
  [0, 0, 1],
  [0, 1, 0],
  [0, 1, 0],
  [0, 1, 0],
  [0, 0, 1],
  [1, 0, 0],
]);
const TOOL_OFFSET_M = Object.freeze([0.15584, 0, 0]);

function multiply3(first, second) {
  return [
    [
      first[0][0] * second[0][0] + first[0][1] * second[1][0] + first[0][2] * second[2][0],
      first[0][0] * second[0][1] + first[0][1] * second[1][1] + first[0][2] * second[2][1],
      first[0][0] * second[0][2] + first[0][1] * second[1][2] + first[0][2] * second[2][2],
    ],
    [
      first[1][0] * second[0][0] + first[1][1] * second[1][0] + first[1][2] * second[2][0],
      first[1][0] * second[0][1] + first[1][1] * second[1][1] + first[1][2] * second[2][1],
      first[1][0] * second[0][2] + first[1][1] * second[1][2] + first[1][2] * second[2][2],
    ],
    [
      first[2][0] * second[0][0] + first[2][1] * second[1][0] + first[2][2] * second[2][0],
      first[2][0] * second[0][1] + first[2][1] * second[1][1] + first[2][2] * second[2][1],
      first[2][0] * second[0][2] + first[2][1] * second[1][2] + first[2][2] * second[2][2],
    ],
  ];
}

function rotateVector(rotation, vector) {
  return [
    rotation[0][0] * vector[0] + rotation[0][1] * vector[1] + rotation[0][2] * vector[2],
    rotation[1][0] * vector[0] + rotation[1][1] * vector[1] + rotation[1][2] * vector[2],
    rotation[2][0] * vector[0] + rotation[2][1] * vector[1] + rotation[2][2] * vector[2],
  ];
}

function axisAngle(axis, angleRad) {
  const [x, y, z] = axis;
  const cosine = Math.cos(angleRad);
  const sine = Math.sin(angleRad);
  const complement = 1 - cosine;
  return [
    [cosine + x * x * complement, x * y * complement - z * sine, x * z * complement + y * sine],
    [y * x * complement + z * sine, cosine + y * y * complement, y * z * complement - x * sine],
    [z * x * complement - y * sine, z * y * complement + x * sine, cosine + z * z * complement],
  ];
}

function forwardKinematicsPosition(jointsDeg) {
  if (!Array.isArray(jointsDeg) || jointsDeg.length !== 6 || !jointsDeg.every(Number.isFinite)) {
    throw new TypeError('forward kinematics requires six finite joint angles');
  }
  let rotation = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  const position = [0, 0, 0];
  for (let index = 0; index < 6; index += 1) {
    const translated = rotateVector(rotation, JOINT_ORIGINS_M[index]);
    position[0] += translated[0];
    position[1] += translated[1];
    position[2] += translated[2];
    rotation = multiply3(
      rotation,
      axisAngle(JOINT_AXES[index], jointsDeg[index] * Math.PI / 180)
    );
  }
  const tool = rotateVector(rotation, TOOL_OFFSET_M);
  return [position[0] + tool[0], position[1] + tool[1], position[2] + tool[2]];
}

module.exports = {
  JOINT_AXES,
  JOINT_ORIGINS_M,
  TOOL_OFFSET_M,
  forwardKinematicsPosition,
};
