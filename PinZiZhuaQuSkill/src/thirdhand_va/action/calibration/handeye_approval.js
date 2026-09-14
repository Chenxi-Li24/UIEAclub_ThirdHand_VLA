'use strict';

const crypto = require('node:crypto');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function contentId(bytes) {
  if (!Buffer.isBuffer(bytes) && !(bytes instanceof Uint8Array)) {
    throw new TypeError('evidence_bytes_invalid');
  }
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function approveHandeyeArtifact({
  calibration,
  calibrationBytes,
  report,
  reportBytes,
  measuredErrorMm,
  operatorConfirmed = false,
  approvedAt = new Date().toISOString(),
} = {}) {
  if (operatorConfirmed !== true) throw new TypeError('operator_confirmation_required');
  if (!Number.isFinite(measuredErrorMm) || measuredErrorMm < 0) {
    throw new TypeError('measured_error_mm_invalid');
  }
  if (measuredErrorMm > 10) throw new TypeError('physical_error_exceeds_10mm');
  if (!calibration || typeof calibration !== 'object' || Array.isArray(calibration) ||
      calibration.schema !== 'thirdhand-handeye-calibration-v3' ||
      calibration.robot_state_semantics !== 'T_base_flange' ||
      calibration.extrinsic_semantics !== 'T_flange_camera' ||
      calibration.numerically_validated !== true ||
      calibration.approved_for_bottle_grasp !== false ||
      calibration.camera_mount_id_activation !== false ||
      calibration.activated_camera_mount_id !== null ||
      typeof calibration.camera?.camera_mount_id !== 'string' ||
      !calibration.camera.camera_mount_id) {
    throw new TypeError('pending_calibration_invalid');
  }
  const limit = calibration.physical_validation
    ?.required_3d_point_or_grasp_error_m_max;
  if (!Number.isFinite(limit) || limit <= 0 || limit > 0.010) {
    throw new TypeError('physical_error_limit_invalid');
  }
  if (!report || typeof report !== 'object' || Array.isArray(report) ||
      report.schema !== 'thirdhand-handeye-pregrasp-validation-v2' ||
      report.validation_mode !== 'measured_3d_clearance' ||
      !SHA256_ID.test(report.calibration_id || '') ||
      report.gripper_commanded !== false || report.commands_descent !== false ||
      report.collision_free !== true || report.returned_home !== true ||
      report.software_cleanup_acknowledged !== true ||
      !['simulation', 'vendor_cleanup_returned'].includes(
        report.cleanup_confirmation_mode
      ) || report.depower_independently_confirmed !== false ||
      report.requires_operator_confirmation !== true ||
      typeof report.overlay_file !== 'string' || !report.overlay_file) {
    throw new TypeError('pregrasp_validation_report_invalid');
  }
  if (report.calibration_id !== contentId(calibrationBytes)) {
    throw new TypeError('calibration_evidence_mismatch');
  }
  if (!(reportBytes instanceof Uint8Array) || !SHA256_ID.test(contentId(reportBytes))) {
    throw new TypeError('pregrasp_validation_report_bytes_invalid');
  }
  if (typeof approvedAt !== 'string' || !Number.isFinite(Date.parse(approvedAt))) {
    throw new TypeError('approved_at_invalid');
  }
  const approved = JSON.parse(JSON.stringify(calibration));
  approved.camera_mount_id_activation = true;
  approved.activated_camera_mount_id = approved.camera.camera_mount_id;
  approved.approved_for_bottle_grasp = true;
  approved.physical_validation = {
    status: 'passed',
    measured_error_m: measuredErrorMm / 1000,
    required_3d_point_or_grasp_error_m_max: limit,
    evidence_report_id: contentId(reportBytes),
    approved_at: new Date(approvedAt).toISOString(),
  };
  return deepFreeze(approved);
}

module.exports = { approveHandeyeArtifact, contentId };
