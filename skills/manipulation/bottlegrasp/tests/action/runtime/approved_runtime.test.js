'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  loadApprovedRuntimeEvidence,
  sameRuntimeEvidence,
} = require('../../../src/thirdhand_va/action/runtime/approved_runtime');

function writeArtifacts(directory, overrides = {}) {
  const visionPath = path.join(directory, 'vision.yaml');
  const calibrationPath = path.join(directory, 'handeye.json');
  fs.writeFileSync(visionPath, [
    'camera_serial: "camera-1"',
    'camera_registration_id: "registration-1"',
    'camera_mount_id: "mount-1"',
    'grounding_model: "debug/grounding"',
    `grounding_revision: "${'1'.repeat(40)}"`,
    `grounding_weights_sha256: "sha256:${'a'.repeat(64)}"`,
    'sam_model: "debug/sam"',
    `sam_revision: "${'2'.repeat(40)}"`,
    `sam_weights_sha256: "sha256:${'b'.repeat(64)}"`,
    '',
  ].join('\n'));
  const calibration = {
    schema: 'thirdhand-handeye-calibration-v3',
    robot_state_semantics: 'T_base_flange',
    extrinsic_semantics: 'T_flange_camera',
    T_flange_camera: { matrix_4x4: [
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
    ] },
    camera: {
      camera_serial: 'camera-1', registration_id: 'registration-1',
      camera_mount_id: 'mount-1',
    },
    numerically_validated: true,
    camera_mount_id_activation: true,
    activated_camera_mount_id: 'mount-1',
    approved_for_bottle_grasp: true,
    physical_validation: {
      status: 'passed', measured_error_m: 0.008,
      required_3d_point_or_grasp_error_m_max: 0.010,
    },
    ...overrides,
  };
  fs.writeFileSync(calibrationPath, `${JSON.stringify(calibration, null, 2)}\n`);
  return { visionPath, calibrationPath };
}

test('approved runtime evidence is content-bound to strict vision and calibration files', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'va-approved-runtime-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const files = writeArtifacts(directory);

  const evidence = loadApprovedRuntimeEvidence(files);

  assert.equal(evidence.camera_serial, 'camera-1');
  assert.equal(evidence.registration_id, 'registration-1');
  assert.equal(evidence.camera_mount_id, 'mount-1');
  assert.match(evidence.vision_config_id, /^sha256:[0-9a-f]{64}$/);
  assert.match(evidence.calibration_id, /^sha256:[0-9a-f]{64}$/);
  assert.equal(evidence.calibration_approved, true);
  assert.equal(sameRuntimeEvidence(evidence, structuredClone(evidence)), true);
  assert.equal(sameRuntimeEvidence(evidence, {
    ...structuredClone(evidence), calibration_id: `sha256:${'f'.repeat(64)}`,
  }), false);
});

test('runtime rejects legacy tool-TCP calibration even when its booleans say approved', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'va-runtime-v2-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const files = writeArtifacts(directory, {
    schema: 'thirdhand-handeye-calibration-v2',
    T_flange_camera: undefined,
    T_tool_camera: { matrix_4x4: [
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
    ] },
    tcp_semantics: 'configured_tool_tcp',
  });

  assert.throws(() => loadApprovedRuntimeEvidence(files), /calibration contract is invalid/);
});

test('runtime approval rejects relaxed physical gates or camera identity mismatch', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'va-runtime-reject-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  let files = writeArtifacts(directory, {
    physical_validation: {
      status: 'passed', measured_error_m: 0.008,
      required_3d_point_or_grasp_error_m_max: 0.02,
    },
  });
  assert.throws(() => loadApprovedRuntimeEvidence(files), /calibration is not approved/);

  files = writeArtifacts(directory);
  const calibration = JSON.parse(fs.readFileSync(files.calibrationPath, 'utf8'));
  calibration.camera.camera_mount_id = 'other-mount';
  calibration.activated_camera_mount_id = 'other-mount';
  fs.writeFileSync(files.calibrationPath, JSON.stringify(calibration));
  assert.throws(() => loadApprovedRuntimeEvidence(files), /camera identity mismatch/);
});
