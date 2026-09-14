#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const { RobotClient } = require('../../src/thirdhand_va/action/adapters/robot_client');
const { GraspController } = require('../../src/thirdhand_va/action/grasp/grasp_controller');

function parseArgs(argv) {
  if (argv.length === 0) return { fixture: null };
  if (argv.length === 2 && argv[0] === '--fixture' && argv[1]) {
    return { fixture: argv[1] };
  }
  throw new TypeError('usage: debug_grasp.js [--fixture approved-plan.json]');
}

function disabledSmoke() {
  const commands = [];
  const robotClient = new RobotClient({
    transport: command => { commands.push(command); return true; },
  });
  const controller = new GraspController({ robotClient });
  const result = controller.start({ executionEnabled: false });
  return { result, sent_commands: commands.length, robot_control_enabled: false };
}

function runFixture(fixturePath) {
  const plan = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  const commands = [];
  const statuses = [];
  let sequence = 0;
  const robotClient = new RobotClient({
    transport: command => { commands.push(command); return true; },
  });
  const controller = new GraspController({
    robotClient,
    getRobotState: () => ({ connected: true, healthy: true, stateFresh: true }),
    idFactory: () => `debug-grasp-${++sequence}`,
    onStatus: status => statuses.push({
      ...status,
      simulation: true,
      robot_control_enabled: false,
    }),
  });
  const started = controller.start(plan);
  while (controller.active) {
    const command = commands.at(-1);
    controller.onRobotEvent({
      type: 'command_complete',
      command: command.cmd,
      request_id: command.request_id,
      reached: command.source === 'grasp:close' ? false : true,
      actual_width_m: command.source === 'grasp:close' ? 0.040
        : command.source === 'grasp:release' ? 0.080 : undefined,
      actualJointsDeg: command.source === 'grasp:return_home'
        ? [...plan.homeJointsDeg] : undefined,
      robot_healthy: true,
    });
  }
  return {
    started,
    command_sources: commands.map(command => command.source),
    fake_robot_commands: commands,
    statuses,
    final: controller.snapshot(),
    robot_control_enabled: false,
  };
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  const payload = args.fixture === null ? disabledSmoke() : runFixture(args.fixture);
  console.log(JSON.stringify(payload));
  return 0;
}

if (require.main === module) {
  try { process.exitCode = main(); } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}

module.exports = { main, parseArgs, runFixture };
