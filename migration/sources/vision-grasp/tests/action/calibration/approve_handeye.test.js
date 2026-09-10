'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const test = require('node:test');

const { approveHandeyeArtifact } = require(
  '../../../src/thirdhand_va/action/calibration/handeye_approval'
);
const { parseArgs } = require('../../../scripts/action/approve_handeye_pregrasp');

function contentId(bytes) {
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function fixture() {
  const calibration = {
    schema: 'thirdhand-handeye-calibration-v3',
    robot_state_semantics: 'T_base_flange',
    extrinsic_semantics: 'T_flange_camera',
    numerically_validated: true,
    camera: {
      camera_serial: 'camera-1',
      registration_id: 'registration-1',
      camera_mount_id: 'mount-1',
    },
    camera_mount_id_activation: false,
    activated_camera_mount_id: null,
    approved_for_bottle_grasp: false,
    physical_validation: {
      status: 'pending', measured_error_m: null,
      required_3d_point_or_grasp_error_m_max: 0.010,
    },
    T_flange_camera: { matrix_4x4: [
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
    ] },
  };
  const calibrationBytes = Buffer.from(`${JSON.stringify(calibration)}\n`);
  const report = {
    schema: 'thirdhand-handeye-pregrasp-validation-v2',
    validation_mode: 'measured_3d_clearance',
    calibration_id: contentId(calibrationBytes),
    gripper_commanded: false,
    commands_descent: false,
    collision_free: true,
    returned_home: true,
    software_cleanup_acknowledged: true,
    cleanup_confirmation_mode: 'vendor_cleanup_returned',
    depower_independently_confirmed: false,
    requires_operator_confirmation: true,
    overlay_file: 'overlay.jpg',
  };
  const reportBytes = Buffer.from(`${JSON.stringify(report)}\n`);
  return { calibration, calibrationBytes, report, reportBytes };
}

test('explicit measured hover approval activates only the matching camera mount', () => {
  const input = fixture();

  const approved = approveHandeyeArtifact({
    ...input,
    measuredErrorMm: 7.5,
    operatorConfirmed: true,
    approvedAt: '2026-08-23T12:00:00.000Z',
  });

  assert.equal(approved.camera_mount_id_activation, true);
  assert.equal(approved.activated_camera_mount_id, 'mount-1');
  assert.equal(approved.approved_for_bottle_grasp, true);
  assert.deepEqual(approved.physical_validation, {
    status: 'passed',
    measured_error_m: 0.0075,
    required_3d_point_or_grasp_error_m_max: 0.010,
    evidence_report_id: contentId(input.reportBytes),
    approved_at: '2026-08-23T12:00:00.000Z',
  });
  assert.equal(Object.isFrozen(approved), true);
});

test('approval rejects missing confirmation excessive error and mismatched evidence', () => {
  const input = fixture();
  assert.throws(() => approveHandeyeArtifact({
    ...input, measuredErrorMm: 4, operatorConfirmed: false,
  }), /operator_confirmation_required/);
  assert.throws(() => approveHandeyeArtifact({
    ...input, measuredErrorMm: 10.1, operatorConfirmed: true,
  }), /physical_error_exceeds_10mm/);
  assert.throws(() => approveHandeyeArtifact({
    ...input,
    report: { ...input.report, calibration_id: `sha256:${'f'.repeat(64)}` },
    measuredErrorMm: 4,
    operatorConfirmed: true,
  }), /calibration_evidence_mismatch/);
  assert.throws(() => approveHandeyeArtifact({
    ...input,
    report: { ...input.report, depower_independently_confirmed: true },
    measuredErrorMm: 4,
    operatorConfirmed: true,
  }), /pregrasp_validation_report_invalid/);
});

test('approval rejects the legacy report format that produced an unsafe descent', () => {
  const input = fixture();
  assert.throws(() => approveHandeyeArtifact({
    ...input,
    report: {
      ...input.report,
      schema: 'thirdhand-handeye-pregrasp-validation-v1',
    },
    measuredErrorMm: 4,
    operatorConfirmed: true,
  }), /pregrasp_validation_report_invalid/);
});

test('approval CLI requires the explicit operator confirmation flag', () => {
  const args = parseArgs([
    '--report', 'artifacts/action/commissioning/report.json',
    '--measured-error-mm', '8.2',
    '--operator-confirmed-hover',
  ]);

  assert.equal(args.measuredErrorMm, 8.2);
  assert.equal(args.operatorConfirmed, true);
  assert.throws(() => parseArgs(['--measured-error-mm', '8']), /--report is required/);
});
