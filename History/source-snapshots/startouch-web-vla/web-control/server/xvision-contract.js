'use strict';

const HASH_PATTERN = /^sha256:[0-9a-f]{64}$/;

function finiteNumber(value) {
  if (value === null || value === undefined || typeof value === 'boolean' || value === '') {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function finiteVector(value) {
  if (!Array.isArray(value) || value.length !== 3) return null;
  const vector = value.map(finiteNumber);
  return vector.every(item => item !== null) ? vector : null;
}

function nonNegativeInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : null;
}

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function boundedStrings(value, maxItems = 32) {
  if (!Array.isArray(value)) return [];
  return value
    .filter(item => typeof item === 'string')
    .slice(0, maxItems)
    .map(item => item.slice(0, 128));
}

function spatialLabel(leftOrdinal, rightOrdinal) {
  const left = positiveInteger(leftOrdinal);
  const right = positiveInteger(rightOrdinal);
  if (left === null || right === null) return null;
  return `L${left}/R${right}`;
}

function selectionMatches(selection, target) {
  if (!selection || !['left', 'right'].includes(selection.side)) return false;
  const requested = positiveInteger(selection.ordinal);
  if (requested === null) return false;
  return selection.side === 'left'
    ? positiveInteger(target.left_ordinal) === requested
    : positiveInteger(target.right_ordinal) === requested;
}

function normalizeDisplayTarget(event, target, selectedCount) {
  const preview = target && typeof target.grasp_preview === 'object'
    ? target.grasp_preview
    : null;
  const selected = target?.selected === true;
  const matches = selected && selectionMatches(event.selection, target);
  const blockers = boundedStrings(preview?.blockers);
  if (selectedCount !== 1 && selected) blockers.push('selected_target_ambiguous');
  if (selected && !matches) blockers.push('selection_mismatch');
  if (selected && event.robot_control_enabled !== true) {
    blockers.push('physical_grasp_execution_locked');
  }
  const graspM = finiteVector(preview?.grasp_xyz_m);
  const cameraDepth = selected ? finiteVector(event.pose?.point_m)?.[2] : null;
  const widthM = finiteNumber(preview?.width_m ?? event.pose?.width_m);
  const depthValidRatio = finiteNumber(
    preview?.central_fraction ?? event.pose?.depth_valid_ratio
  );
  const id = nonNegativeInteger(target?.identity_id) ??
    nonNegativeInteger(target?.detection_id);
  return {
    id,
    detectionId: nonNegativeInteger(target?.detection_id),
    identityId: nonNegativeInteger(target?.identity_id),
    label: typeof target?.label === 'string' ? target.label.slice(0, 64) : 'object',
    conf: finiteNumber(target?.score) ?? 0,
    selected,
    leftOrdinal: positiveInteger(target?.left_ordinal),
    rightOrdinal: positiveInteger(target?.right_ordinal),
    spatialLabel: spatialLabel(target?.left_ordinal, target?.right_ordinal),
    position_m: graspM,
    depth_m: cameraDepth,
    depthValidRatio,
    graspWidthM: widthM,
    previewIdShort: HASH_PATTERN.test(preview?.preview_id || '')
      ? `${preview.preview_id.slice(0, 19)}…`
      : null,
    blockers: [...new Set(blockers)],
    reasons: boundedStrings(target?.reasons),
    actionable: selected && matches && selectedCount === 1 &&
      event.robot_control_enabled === true && target?.actionable === true &&
      preview?.allowed === true && blockers.length === 0,
  };
}

function normalizeTrustedTarget(event, target, selectedCount) {
  if (selectedCount !== 1 || !selectionMatches(event.selection, target)) return null;
  const preview = target && typeof target.grasp_preview === 'object'
    ? target.grasp_preview
    : null;
  const observedAtMs = finiteNumber(target?.observed_at_ms ?? event.ts);
  const eventAtMs = finiteNumber(event.ts);
  const graspM = finiteVector(preview?.grasp_xyz_m);
  const pregraspM = finiteVector(preview?.pregrasp_xyz_m);
  const retreatM = finiteVector(preview?.retreat_xyz_m);
  const widthM = finiteNumber(preview?.width_m);
  const previewId = HASH_PATTERN.test(preview?.preview_id || '')
    ? preview.preview_id
    : null;
  const calibrationId = HASH_PATTERN.test(preview?.calibration_id || '')
    ? preview.calibration_id
    : null;
  if (
    observedAtMs === null || eventAtMs === null ||
    !graspM || !pregraspM || !retreatM || widthM === null ||
    !previewId || !calibrationId
  ) return null;
  const blockers = boundedStrings(preview?.blockers);
  const safetyApproved = target?.safety_approved === true && blockers.length === 0;
  const previewAllowed = preview?.allowed === true;
  const actionable = event.robot_control_enabled === true &&
    target?.actionable === true && previewAllowed && safetyApproved;
  if (!actionable) return null;
  return Object.freeze({
    id: nonNegativeInteger(target?.identity_id) ?? nonNegativeInteger(target?.detection_id),
    detectionId: nonNegativeInteger(target?.detection_id),
    identityId: nonNegativeInteger(target?.identity_id),
    selected: true,
    leftOrdinal: positiveInteger(target?.left_ordinal),
    rightOrdinal: positiveInteger(target?.right_ordinal),
    observedAtMs,
    eventAtMs,
    previewId,
    calibrationId,
    graspM: Object.freeze(graspM),
    pregraspM: Object.freeze(pregraspM),
    retreatM: Object.freeze(retreatM),
    widthM,
    yawRad: finiteNumber(preview?.yaw_rad),
    actionable,
    calibrationValidated: target?.calibration_validated === true,
    depthValid: target?.depth_valid === true,
    identityConfirmed: target?.identity_confirmed === true,
    armStationary: target?.arm_stationary === true,
    safetyApproved,
    previewAllowed,
  });
}

function normalizeXVisionEvent(event) {
  if (!event || typeof event !== 'object' ||
      event.type !== 'detection_result' ||
      event.schema !== 'thirdhand-va-detection-v2') {
    throw new TypeError('Unsupported XVisio detection schema');
  }
  const targets = Array.isArray(event.targets) ? event.targets.slice(0, 256) : [];
  const selected = targets.filter(target => target?.selected === true);
  const displayTargets = targets.map(target => (
    normalizeDisplayTarget(event, target, selected.length)
  ));
  const trustedTarget = selected.length === 1
    ? normalizeTrustedTarget(event, selected[0], selected.length)
    : null;
  return {
    displayEvent: {
      type: 'detection_result',
      schema: event.schema,
      ts: finiteNumber(event.ts),
      status: typeof event.status === 'string' ? event.status.slice(0, 64) : 'unknown',
      selection: event.selection && typeof event.selection === 'object'
        ? {
            side: ['left', 'right'].includes(event.selection.side)
              ? event.selection.side
              : null,
            ordinal: positiveInteger(event.selection.ordinal),
          }
        : null,
      objects: displayTargets,
      targets: displayTargets,
      robotExecutionEnabled: event.robot_control_enabled === true,
      hardwareValidation: typeof event.hardware_validation === 'string'
        ? event.hardware_validation.slice(0, 64)
        : 'unknown',
      reasons: boundedStrings(event.reasons),
    },
    trustedTarget,
  };
}

module.exports = {
  HASH_PATTERN,
  finiteVector,
  normalizeXVisionEvent,
  selectionMatches,
  spatialLabel,
};
