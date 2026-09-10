#!/usr/bin/env node
'use strict';

const fs = require('node:fs');

const {
  deriveExecutionGeometry,
} = require('../../src/thirdhand_va/action/grasp/execution_plan');

function parseArgs(argv) {
  if (argv.length !== 2 || argv[0] !== '--fixture' || !argv[1]) {
    throw new TypeError('usage: debug_execution_plan.js --fixture FILE');
  }
  return { fixture: argv[1] };
}

function debugFixture(fixturePath) {
  const fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8'));
  if (fixture.schema !== 'thirdhand-va-full-cycle-fixture-v1') {
    throw new TypeError('full-cycle fixture schema mismatch');
  }
  const detectedGraspPointM = fixture.point_m;
  const offset = fixture.flange_offset_base_m;
  if (!Array.isArray(detectedGraspPointM) || !Array.isArray(offset)) {
    throw new TypeError('fixture grasp geometry is incomplete');
  }
  const commandedFlangeGraspM = detectedGraspPointM.map(
    (value, index) => Number((value + offset[index]).toFixed(12))
  );
  const config = {
    motion: { pregrasp_offset_m: 0.10, lift_height_m: 0.12 },
    grasp: { flange_offset_base_m: offset, offset_validated: true },
    place: {
      strategy: 'fixed_xy_keep_grasp_z',
      validated: true,
      fixed_xy_m: fixture.fixed_place_xy_m,
      grasp_z_range_m: fixture.grasp_z_range_m,
      vertical_clearance_m: fixture.vertical_clearance_m,
    },
  };
  const geometry = deriveExecutionGeometry({
    detectedGraspPointM,
    commandedFlangeGraspM,
    approachBase: [1, 0, 0],
  }, config);
  return {
    schema: 'thirdhand-execution-geometry-debug-v1',
    strategy: config.place.strategy,
    detected_grasp_point_m: geometry.detectedGraspM,
    commanded_flange_grasp_point_m: geometry.commandedFlangeGraspM,
    flange_offset_base_m: geometry.flangeOffsetBaseM,
    waypoints: {
      pregrasp_m: geometry.pregraspM,
      commanded_grasp_m: geometry.commandedFlangeGraspM,
      lift_m: geometry.liftM,
      pre_place_m: geometry.prePlaceM,
      place_m: geometry.placeM,
      retreat_m: geometry.retreatM,
    },
    units: { position: 'm', orientation: 'rad' },
    blockers: [],
    hardware_connected: false,
    robot_control_enabled: false,
  };
}

function main(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  console.log(JSON.stringify(debugFixture(args.fixture)));
  return 0;
}

if (require.main === module) {
  try { process.exitCode = main(); } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 2;
  }
}

module.exports = { debugFixture, main, parseArgs };
