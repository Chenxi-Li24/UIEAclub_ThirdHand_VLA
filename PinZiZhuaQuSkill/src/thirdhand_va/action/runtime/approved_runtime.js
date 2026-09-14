'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const YAML = require('yaml');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;
const REVISION = /^[0-9a-f]{40}$/;
const MODEL_FIELDS = Object.freeze([
  'vision_config_id', 'camera_registration_id', 'camera_mount_id',
  'grounding_model', 'grounding_revision', 'grounding_weights_sha256',
  'sam_model', 'sam_revision', 'sam_weights_sha256',
]);

function contentId(bytes) {
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function sameModelEvidence(left, right) {
  return left && right && MODEL_FIELDS.every(field => left[field] === right[field]);
}

function validRuntimeEvidence(value) {
  const models = value?.model_provenance;
  return typeof value?.camera_serial === 'string' && value.camera_serial.length > 0 &&
    typeof value.registration_id === 'string' && value.registration_id.length > 0 &&
    typeof value.camera_mount_id === 'string' && value.camera_mount_id.length > 0 &&
    SHA256_ID.test(value.vision_config_id || '') &&
    SHA256_ID.test(value.calibration_id || '') && value.calibration_approved === true &&
    models?.vision_config_id === value.vision_config_id &&
    models.camera_registration_id === value.registration_id &&
    models.camera_mount_id === value.camera_mount_id &&
    typeof models.grounding_model === 'string' && models.grounding_model.length > 0 &&
    typeof models.sam_model === 'string' && models.sam_model.length > 0 &&
    REVISION.test(models.grounding_revision || '') &&
    REVISION.test(models.sam_revision || '') &&
    SHA256_ID.test(models.grounding_weights_sha256 || '') &&
    SHA256_ID.test(models.sam_weights_sha256 || '');
}

function copyRuntimeEvidence(value) {
  return Object.freeze({
    ...value,
    model_provenance: Object.freeze({ ...value.model_provenance }),
  });
}

function sameRuntimeEvidence(left, right) {
  return validRuntimeEvidence(left) && validRuntimeEvidence(right) &&
    ['camera_serial', 'registration_id', 'camera_mount_id', 'vision_config_id',
      'calibration_id', 'calibration_approved'].every(field => left[field] === right[field]) &&
    sameModelEvidence(left.model_provenance, right.model_provenance);
}

function visionResultMatchesRuntime(result, runtime) {
  if (!result || result.cameraSerial !== runtime.camera_serial ||
      result.registrationId !== runtime.registration_id ||
      result.visionConfigId !== runtime.vision_config_id ||
      !sameModelEvidence(result.modelProvenance, runtime.model_provenance) ||
      !Array.isArray(result.targets)) return false;
  return result.targets.every(target => {
    const preview = target?.graspPreview ?? target?.preview;
    if (preview === undefined || preview === null) return true;
    return (preview.calibration_id ?? preview.calibrationId) === runtime.calibration_id &&
      (preview.vision_config_id ?? preview.visionConfigId) === runtime.vision_config_id &&
      sameModelEvidence(
        preview.model_provenance ?? preview.modelProvenance,
        runtime.model_provenance,
      );
  });
}

function rigidTransform(value) {
  if (!Array.isArray(value) || value.length !== 4 ||
      value.some(row => !Array.isArray(row) || row.length !== 4 ||
        !row.every(Number.isFinite)) ||
      value[3].some((item, index) => Math.abs(item - [0, 0, 0, 1][index]) > 1e-9)) {
    return false;
  }
  const rotation = value.slice(0, 3).map(row => row.slice(0, 3));
  for (let left = 0; left < 3; left += 1) {
    for (let right = 0; right < 3; right += 1) {
      const dot = rotation.reduce((sum, row) => sum + row[left] * row[right], 0);
      if (Math.abs(dot - (left === right ? 1 : 0)) > 1e-7) return false;
    }
  }
  const [a, b, c] = rotation;
  const determinant = a[0] * (b[1] * c[2] - b[2] * c[1]) -
    a[1] * (b[0] * c[2] - b[2] * c[0]) +
    a[2] * (b[0] * c[1] - b[1] * c[0]);
  return Math.abs(determinant - 1) <= 1e-7;
}

function loadApprovedRuntimeEvidence({ visionPath, visionConfigPath, calibrationPath } = {}) {
  const resolvedVisionPath = visionConfigPath || visionPath;
  if (typeof resolvedVisionPath !== 'string' || !resolvedVisionPath ||
      typeof calibrationPath !== 'string' || !calibrationPath) {
    throw new TypeError('approved runtime artifact paths are required');
  }
  const visionBytes = fs.readFileSync(resolvedVisionPath);
  const vision = YAML.parse(visionBytes.toString('utf8'));
  const cameraFields = ['camera_serial', 'camera_registration_id', 'camera_mount_id'];
  const modelFields = [
    'grounding_model', 'grounding_revision', 'grounding_weights_sha256',
    'sam_model', 'sam_revision', 'sam_weights_sha256',
  ];
  if (!vision || typeof vision !== 'object' || Array.isArray(vision) ||
      cameraFields.some(field => typeof vision[field] !== 'string' || !vision[field]) ||
      ['grounding_model', 'sam_model'].some(field =>
        typeof vision[field] !== 'string' || !vision[field].includes('/')) ||
      !REVISION.test(vision.grounding_revision || '') ||
      !REVISION.test(vision.sam_revision || '') ||
      !SHA256_ID.test(vision.grounding_weights_sha256 || '') ||
      !SHA256_ID.test(vision.sam_weights_sha256 || '') ||
      modelFields.some(field => !Object.hasOwn(vision, field))) {
    throw new TypeError('vision approval manifest is invalid');
  }

  const calibrationBytes = fs.readFileSync(calibrationPath);
  const calibration = JSON.parse(calibrationBytes.toString('utf8'));
  const physical = calibration.physical_validation;
  const camera = calibration.camera;
  if (calibration.schema !== 'thirdhand-handeye-calibration-v3' ||
      calibration.robot_state_semantics !== 'T_base_flange' ||
      calibration.extrinsic_semantics !== 'T_flange_camera' ||
      !rigidTransform(calibration.T_flange_camera?.matrix_4x4)) {
    throw new TypeError('calibration contract is invalid');
  }
  if (camera?.camera_serial !== vision.camera_serial ||
      camera?.registration_id !== vision.camera_registration_id ||
      camera?.camera_mount_id !== vision.camera_mount_id) {
    throw new TypeError('calibration camera identity mismatch');
  }
  const measured = physical?.measured_error_m;
  const limit = physical?.required_3d_point_or_grasp_error_m_max;
  const approved = calibration.numerically_validated === true &&
    calibration.camera_mount_id_activation === true &&
    calibration.activated_camera_mount_id === camera.camera_mount_id &&
    calibration.approved_for_bottle_grasp === true &&
    physical?.status === 'passed' && Number.isFinite(measured) && measured >= 0 &&
    Number.isFinite(limit) && limit > 0 && limit <= 0.010 &&
    measured <= limit && measured <= 0.010;
  if (!approved) throw new TypeError('calibration is not approved');

  const visionConfigId = contentId(visionBytes);
  return copyRuntimeEvidence({
    camera_serial: vision.camera_serial,
    registration_id: vision.camera_registration_id,
    camera_mount_id: vision.camera_mount_id,
    vision_config_id: visionConfigId,
    calibration_id: contentId(calibrationBytes),
    calibration_approved: true,
    model_provenance: {
      vision_config_id: visionConfigId,
      camera_registration_id: vision.camera_registration_id,
      camera_mount_id: vision.camera_mount_id,
      grounding_model: vision.grounding_model,
      grounding_revision: vision.grounding_revision,
      grounding_weights_sha256: vision.grounding_weights_sha256,
      sam_model: vision.sam_model,
      sam_revision: vision.sam_revision,
      sam_weights_sha256: vision.sam_weights_sha256,
    },
  });
}

module.exports = {
  copyRuntimeEvidence,
  loadApprovedRuntimeEvidence,
  sameModelEvidence,
  sameRuntimeEvidence,
  validRuntimeEvidence,
  visionResultMatchesRuntime,
};
