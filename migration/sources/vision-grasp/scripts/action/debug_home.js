#!/usr/bin/env node
'use strict';

const { evaluateHomeState } = require(
  '../../src/thirdhand_va/action/safety/home_gate'
);

function parseJointVector(value, name) {
  const joints = typeof value === 'string' ? value.split(',').map(Number) : null;
  if (!Array.isArray(joints) || joints.length !== 6 || !joints.every(Number.isFinite)) {
    throw new TypeError(`${name} must contain six comma-separated degrees`);
  }
  return joints;
}

function parseArgs(argv) {
  const result = { home: null, actual: null, tolerance: null };
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === '--home') result.home = parseJointVector(argv[++index], '--home');
    else if (argv[index] === '--actual') {
      result.actual = parseJointVector(argv[++index], '--actual');
    } else if (argv[index] === '--tolerance') result.tolerance = Number(argv[++index]);
    else throw new TypeError(`unknown argument: ${argv[index]}`);
  }
  if (result.home === null || result.actual === null ||
      !Number.isFinite(result.tolerance)) {
    throw new TypeError(
      'usage: debug_home.js --home J1,J2,J3,J4,J5,J6 ' +
      '--actual J1,J2,J3,J4,J5,J6 --tolerance DEG'
    );
  }
  return result;
}

function run(args) {
  const result = evaluateHomeState({
    robotState: {
      connected: true, healthy: true, stateFresh: true, stationary: true,
      jointsDeg: args.actual,
    },
    homeJointsDeg: args.home,
    toleranceDeg: args.tolerance,
  });
  return {
    schema: 'thirdhand-home-debug-v1',
    home_joints_deg: [...args.home],
    actual_joints_deg: [...args.actual],
    tolerance_deg: args.tolerance,
    joint_errors_deg: result.jointErrorsDeg,
    max_joint_error_deg: result.maxJointErrorDeg,
    allowed: result.allowed,
    blockers: result.blockers,
    hardware_connected: false,
    robot_control_enabled: false,
  };
}

function main(argv = process.argv.slice(2)) {
  console.log(JSON.stringify(run(parseArgs(argv))));
  return 0;
}

if (require.main === module) {
  try { process.exitCode = main(); } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}

module.exports = { main, parseArgs, run };
