#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const { loadActionConfig } = require('../../src/thirdhand_va/action/config');
const { authorizePregraspValidation } = require(
  '../../src/thirdhand_va/action/calibration/pregrasp_validation'
);

function parseArgs(argv) {
  const result = {
    fixture: 'tests/fixtures/action/handeye-clearance.json',
    config: 'configs/action.yaml',
  };
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--fixture' || arg === '--config') {
      const value = argv[++index];
      if (!value) throw new TypeError(`missing value for ${arg}`);
      result[arg === '--fixture' ? 'fixture' : 'config'] = value;
    } else {
      throw new TypeError(`unknown argument: ${arg}`);
    }
  }
  return Object.freeze(result);
}

function main(argv = process.argv.slice(2), write = line => console.log(line)) {
  const args = parseArgs(argv);
  const projectRoot = path.resolve(__dirname, '../..');
  const fixture = JSON.parse(fs.readFileSync(path.resolve(projectRoot, args.fixture), 'utf8'));
  const config = loadActionConfig(path.resolve(projectRoot, args.config));
  const result = authorizePregraspValidation({
    targetId: fixture.target_id,
    target: fixture.target,
    robot: fixture.robot,
    config,
    nowMs: fixture.now_ms,
  });
  write(JSON.stringify({
    mode: 'offline_clearance_plan',
    result,
    hardware_connected: false,
    camera_connected: false,
    robot_control_enabled: false,
  }, null, 2));
  return result.approved === true ? 0 : 1;
}

if (require.main === module) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(error.stack || error.message);
    process.exitCode = 2;
  }
}

module.exports = { main, parseArgs };
