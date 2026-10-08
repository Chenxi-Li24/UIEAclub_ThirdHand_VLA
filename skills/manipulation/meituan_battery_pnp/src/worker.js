'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');

const DEFAULT_POINTS_FILE = path.resolve(__dirname, '../points.md');
const SOURCE_SLOTS = new Set(['A', 'B', 'C', 'D']);
const DESTINATIONS = new Set(['T0', 'P1', 'P2', 'P3']);
const TRANSFER_FLOOR_MM = 146;

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function cells(line) {
  return line.trim().split('|').slice(1, -1).map(cell => cell.trim());
}

function table(markdown, header) {
  const lines = markdown.split(/\r?\n/);
  const start = lines.findIndex(line => cells(line).slice(0, header.length).join('|') === header.join('|'));
  if (start < 0) fail('calibration_invalid', `Missing ${header.join('/')} table`);
  const rows = [];
  for (const line of lines.slice(start + 1)) {
    if (!line.trim().startsWith('|')) break;
    const row = cells(line);
    if (row.every(cell => /^:?-+:?$/.test(cell))) continue;
    rows.push(row);
  }
  return rows;
}

function finiteNumber(raw, label) {
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(raw || '')) {
    fail('calibration_invalid', `Invalid ${label}`);
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) fail('calibration_invalid', `Invalid ${label}`);
  return value;
}

function loadCalibration(file) {
  const markdown = fs.readFileSync(file, 'utf8');
  const points = {};
  for (const row of table(markdown, ['Point', 'J1', 'J2', 'J3', 'J4', 'J5', 'J6'])) {
    const name = row[0];
    if (!/^[A-Z][A-Z0-9_]*$/.test(name || '') || Object.hasOwn(points, name)) {
      fail('calibration_invalid', 'Invalid or duplicate point name');
    }
    points[name] = row.slice(1, 7).map((raw, index) => finiteNumber(raw, `${name}.J${index + 1}`));
    if (points[name].length !== 6) fail('calibration_invalid', `Incomplete point ${name}`);
  }
  const openings = {};
  for (const row of table(markdown, ['Action', 'Target opening'])) {
    const key = { Grasp: 'graspPercent', Release: 'releasePercent' }[row[0]];
    const match = /^(\d+(?:\.\d+)?)%$/.exec(row[1] || '');
    if (!key || !match || Object.hasOwn(openings, key)) fail('calibration_invalid', 'Invalid gripper opening');
    openings[key] = Number(match[1]);
    if (openings[key] < 0 || openings[key] > 100) fail('calibration_invalid', 'Gripper opening out of range');
  }
  const parameters = {};
  const keys = {
    'Pre-contact above': ['preAboveMm', 'mm'],
    'Post-contact above': ['postAboveMm', 'mm'],
    'Lift hold': ['liftHoldMs', 'ms'],
    'Release hold': ['releaseHoldMs', 'ms'],
  };
  for (const row of table(markdown, ['Parameter', 'Value'])) {
    const mapping = keys[row[0]];
    if (!mapping || Object.hasOwn(parameters, mapping[0])) fail('calibration_invalid', 'Invalid workflow parameter');
    const match = new RegExp(`^([0-9]+(?:\\.[0-9]+)?) ${mapping[1]}$`).exec(row[1] || '');
    if (!match) fail('calibration_invalid', `Invalid ${row[0]}`);
    parameters[mapping[0]] = Number(match[1]);
    if (parameters[mapping[0]] <= 0) fail('calibration_invalid', `Invalid ${row[0]}`);
  }
  if (!points.OBSERVE || Object.keys(openings).length !== 2 || Object.keys(parameters).length !== 4) {
    fail('calibration_invalid', 'Required calibration data is incomplete');
  }
  return { points, openings, parameters, digest: createHash('sha256').update(markdown).digest('hex') };
}

function planTransfer(request, { pointsFile = DEFAULT_POINTS_FILE } = {}) {
  if (!request || typeof request !== 'object' || Array.isArray(request)) {
    fail('input_invalid', 'A source slot and destination are required');
  }
  if (!request.source && request.color) {
    fail('vision_resolution_not_connected', 'Color to source-slot resolution is not connected; provide A, B, C, or D');
  }
  if (Object.keys(request).some(key => !['source', 'destination'].includes(key))) {
    fail('input_invalid', 'Only source slot and destination are accepted');
  }
  const source = String(request.source || '').toUpperCase();
  const destination = String(request.destination || '').toUpperCase();
  if (!SOURCE_SLOTS.has(source) || !DESTINATIONS.has(destination)) {
    fail('input_invalid', 'Source must be A/B/C/D and destination T0/P1/P2/P3');
  }
  if (destination === 'T0' && source !== 'A') {
    fail('input_invalid', 'Only Task 1 source A is recorded for T0');
  }
  const sourcePoint = destination === 'T0' ? 'TASK1_A' : `TASK2_${source}`;
  const destinationPoint = destination === 'T0' ? 'TASK1_T0' : `TASK2_${destination}`;
  const { points, openings, parameters, digest } = loadCalibration(pointsFile);
  const sourceBeforePoint = sourcePoint + '_BEFORE';
  const sourceAfterPoint = sourcePoint + '_AFTER';
  const destinationBeforePoint = destinationPoint + '_BEFORE';
  const taughtDestinationAfter = destinationPoint + '_AFTER';
  const destinationAfterPoint = points[taughtDestinationAfter]
    ? taughtDestinationAfter
    : destinationPoint === 'TASK2_P2' ? destinationBeforePoint : taughtDestinationAfter;
  const resolved = {
    sourcePoint, destinationPoint, sourceBeforePoint, sourceAfterPoint,
    destinationBeforePoint, destinationAfterPoint,
  };
  for (const name of Object.values(resolved)) {
    if (!points[name]) fail('calibration_invalid', 'Requested taught point is missing: ' + name);
  }
  const taughtJointsDeg = Object.fromEntries(
    ['OBSERVE', ...new Set(Object.values(resolved))].map(name => [name, points[name]]));
  const jointPoint = (id, point, requires) => ({
    id, kind: 'joint_point', point, jointsDeg: points[point],
    ...(requires ? { requires } : {}),
  });
  return {
    schema: 'thirdhand.meituan-transfer-plan.v1',
    skillId: 'manipulation.meituan-battery-pnp',
    executionReady: false,
    visionResolution: 'not_connected',
    input: { source, destination },
    resolved,
    pointsDigest: digest,
    contactJointsDeg: { source: points[sourcePoint], destination: points[destinationPoint] },
    taughtJointsDeg,
    parameters: { ...parameters, ...openings },
    steps: [
      { id: 'zero_start', kind: 'preset', name: 'zero' },
      jointPoint('observe', 'OBSERVE'),
      jointPoint('source_pre', sourceBeforePoint),
      jointPoint('source_contact', sourcePoint),
      { id: 'grasp', kind: 'gripper', positionPercent: openings.graspPercent },
      jointPoint('source_post', sourceAfterPoint, 'gripper_at_target_and_battery_secured'),
      { id: 'lift_hold', kind: 'hold', durationMs: parameters.liftHoldMs,
        startWhen: 'battery_lifted_and_stable' },
      { id: 'transfer_xy', kind: 'cartesian', motion: 'horizontal_constant_base_z',
        target: { xyFromPoint: destinationBeforePoint, zFromStep: 'source_post' },
        orientationFromPoint: sourceAfterPoint, minBaseZMm: TRANSFER_FLOOR_MM },
      ...(destination === 'P1' ? [] : [jointPoint('destination_pre', destinationBeforePoint)]),
      jointPoint('destination_contact', destinationPoint),
      { id: 'release', kind: 'gripper', positionPercent: openings.releasePercent },
      jointPoint('destination_post', destinationAfterPoint, 'gripper_at_target_and_battery_released'),
      { id: 'release_hold', kind: 'hold', durationMs: parameters.releaseHoldMs,
        startWhen: 'gripper_at_target_and_battery_released_stable' },
      { id: 'zero_finish', kind: 'preset', name: 'zero' },
    ],
  };
}

function status() {
  return { skillId: 'manipulation.meituan-battery-pnp', planningReady: true,
    executionReady: false, visionResolution: 'not_connected' };
}

if (require.main === module) {
  try {
    const [operation, source, destination] = process.argv.slice(2);
    const result = operation === 'status' ? status()
      : operation === 'plan' ? planTransfer({ source, destination })
        : fail('operation_unsupported', 'Use plan <A|B|C|D> <T0|P1|P2|P3> or status');
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } catch (error) {
    process.stderr.write(`${JSON.stringify({ error: error.code || 'planning_failed', message: error.message })}\n`);
    process.exitCode = 1;
  }
}

module.exports = { planTransfer, status, loadCalibration };
