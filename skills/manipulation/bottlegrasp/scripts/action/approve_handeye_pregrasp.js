#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const { approveHandeyeArtifact, contentId } = require(
  '../../src/thirdhand_va/action/calibration/handeye_approval'
);

const USAGE = [
  'usage: approve_handeye_pregrasp.js --report FILE --measured-error-mm N',
  '       --operator-confirmed-hover [options]',
  '  --calibration FILE  pending calibration (default: configs/calibration/lumos-handeye.pending.json)',
  '  --output FILE       approved copy (default: configs/calibration/lumos-handeye.approved.json)',
].join('\n');

function parseArgs(argv) {
  const result = {
    help: false,
    operatorConfirmed: false,
    calibration: 'configs/calibration/lumos-handeye.pending.json',
    report: null,
    output: 'configs/calibration/lumos-handeye.approved.json',
    measuredErrorMm: null,
  };
  const values = new Map([
    ['--calibration', 'calibration'], ['--report', 'report'],
    ['--output', 'output'], ['--measured-error-mm', 'measuredErrorMm'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--help') result.help = true;
    else if (arg === '--operator-confirmed-hover') result.operatorConfirmed = true;
    else if (values.has(arg)) {
      const value = argv[++index];
      if (!value) throw new TypeError(`missing value for ${arg}`);
      result[values.get(arg)] = value;
    } else throw new TypeError(`unknown argument: ${arg}`);
  }
  result.measuredErrorMm = Number(result.measuredErrorMm);
  if (!result.help && !result.report) throw new TypeError('--report is required');
  if (!result.help && (!Number.isFinite(result.measuredErrorMm) ||
      result.measuredErrorMm < 0)) {
    throw new TypeError('--measured-error-mm must be a finite non-negative number');
  }
  return Object.freeze(result);
}

function insideProject(projectRoot, value, name) {
  const resolved = path.resolve(projectRoot, value);
  const relative = path.relative(projectRoot, resolved);
  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new TypeError(`${name} must stay inside bottlegrasp`);
  }
  return resolved;
}

function main(argv = process.argv.slice(2), dependencies = {}) {
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  let args;
  try { args = parseArgs(argv); } catch (error) {
    writeError(error.message);
    return 2;
  }
  if (args.help) {
    write(USAGE);
    return 0;
  }
  try {
    const projectRoot = path.resolve(__dirname, '../..');
    const calibrationPath = insideProject(projectRoot, args.calibration, '--calibration');
    const reportPath = insideProject(projectRoot, args.report, '--report');
    const outputPath = insideProject(projectRoot, args.output, '--output');
    const calibrationBytes = fs.readFileSync(calibrationPath);
    const reportBytes = fs.readFileSync(reportPath);
    const calibration = JSON.parse(calibrationBytes.toString('utf8'));
    const report = JSON.parse(reportBytes.toString('utf8'));
    const overlayPath = path.resolve(path.dirname(reportPath), report.overlay_file || '');
    if (!report.overlay_file || !fs.existsSync(overlayPath) ||
        path.relative(path.dirname(reportPath), overlayPath).startsWith('..')) {
      throw new TypeError('pregrasp_validation_overlay_missing');
    }
    const approved = approveHandeyeArtifact({
      calibration,
      calibrationBytes,
      report,
      reportBytes,
      measuredErrorMm: args.measuredErrorMm,
      operatorConfirmed: args.operatorConfirmed,
    });
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    const outputBytes = Buffer.from(`${JSON.stringify(approved, null, 2)}\n`);
    fs.writeFileSync(outputPath, outputBytes, { flag: 'wx' });
    write(JSON.stringify({
      status: 'approved',
      calibration: outputPath,
      calibration_id: contentId(outputBytes),
      measured_error_mm: args.measuredErrorMm,
      robot_control_enabled: false,
    }));
    return 0;
  } catch (error) {
    writeError(`hand-eye approval failed: ${error.message}`);
    return 2;
  }
}

if (require.main === module) process.exitCode = main();

module.exports = { main, parseArgs };
