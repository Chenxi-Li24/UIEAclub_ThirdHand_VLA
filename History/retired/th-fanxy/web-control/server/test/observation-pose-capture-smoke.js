'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { ObservationPoseCaptureService } = require('../observation-pose-capture-api');

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'observation-capture-'));
const output = path.join(directory, 'captures.json');
let state = {
  simulated: false, connected: true, stateFresh: true, stationary: true,
  jointsDeg: [1, 20, -40, 0, 10, 0],
  tcpPositionM: [0.1, 0.02, 0.5], tcpEulerRad: [0, 0, 1.57], observedAtMs: 1000,
};
const service = new ObservationPoseCaptureService({
  output, catalog: path.join(directory, 'observation-catalog.json'),
  getRobotState: () => state, speedScale: 0.05, nowMs: () => 1100,
});

assert.deepEqual(service.capture({ pose_id: 'table_center' }), {
  accepted: true, poseId: 'table_center', captured: 1, remaining: 4,
});
const written = JSON.parse(fs.readFileSync(output, 'utf8'));
assert.deepEqual(written.captures[0].joints_deg, state.jointsDeg);
assert.equal(written.captures[0].name, 'table_center');
assert.deepEqual(written.captures[0].allowed_start_pose_ids, ['table_center']);
assert.equal(written.captures[0].joint_tolerance_deg, 0.5);
assert.equal(written.captures[0].captured_at, '1970-01-01T00:00:01.100Z');
assert.equal(Object.hasOwn(written.captures[0], 'pose_id'), false);
assert.equal(Object.hasOwn(written.captures[0], 'robot_observed_at_ms'), false);
assert.equal(JSON.stringify(written).includes('move_l'), false);
assert.deepEqual(service.validateCurrentPose({
  pose_id: 'table_center', operator_acknowledged: true,
}), { accepted: true, poseId: 'table_center', maxJointErrorDeg: 0 });
const validated = JSON.parse(fs.readFileSync(output, 'utf8')).captures[0];
assert.deepEqual(validated.path_validation, {
  tested_at: '1970-01-01T00:00:01.100Z', max_joint_error_deg: 0,
  speed_scale: 0.05, operator_acknowledged: true,
});
assert.equal(service.status().lastValidatedPoseId, 'table_center');

state = {
  ...state,
  jointsDeg: [10, 25, -45, 2, 8, 1],
  tcpPositionM: [0.2, 0.15, 0.45],
};
assert.equal(service.capture({ pose_id: 'table_left' }).accepted, true);
let left = JSON.parse(fs.readFileSync(output, 'utf8')).captures
  .find(item => item.name === 'table_left');
assert.deepEqual(left.allowed_start_pose_ids, ['table_left', 'table_center']);
assert.equal(service.validateCurrentPose({
  pose_id: 'table_left', operator_acknowledged: true,
}).accepted, true);
left = JSON.parse(fs.readFileSync(output, 'utf8')).captures
  .find(item => item.name === 'table_left');
assert.equal(left.path_validation.operator_acknowledged, true);

state = { ...state, stationary: false };
assert.deepEqual(service.capture({ pose_id: 'table_right' }), {
  accepted: false, reason: 'robot_not_stationary',
});
assert.deepEqual(service.capture({ pose_id: 'unknown' }), {
  accepted: false, reason: 'pose_id_invalid',
});
state = { ...state, simulated: true, stationary: true };
assert.deepEqual(service.capture({ pose_id: 'table_right' }), {
  accepted: false, reason: 'simulated_robot_forbidden',
});
assert.deepEqual(service.capture({ pose_id: 'table_right', joints: [0, 0, 0, 0, 0, 0] }), {
  accepted: false, reason: 'capture_command_invalid',
});
assert.deepEqual(service.validateCurrentPose({
  pose_id: 'table_center', operator_acknowledged: false,
}), { accepted: false, reason: 'operator_acknowledgement_required' });
assert.equal(service.status().catalogValidated, false);
assert.deepEqual(service.status().capturedPoseIds, ['table_center', 'table_left']);

const simulatorService = new ObservationPoseCaptureService({
  output: path.join(directory, 'simulator-captures.json'),
  catalog: path.join(directory, 'observation-catalog.json'),
  simulationOnly: true,
  getRobotState: () => ({ ...state, simulated: undefined }),
  nowMs: () => 1200,
});
assert.equal(simulatorService.status().robot.simulated, true);
assert.deepEqual(simulatorService.capture({ pose_id: 'table_right' }), {
  accepted: false, reason: 'simulated_robot_forbidden',
});

fs.rmSync(directory, { recursive: true, force: true });
console.log('PASS observation pose capture is read-only, atomic, and server-state-owned');
