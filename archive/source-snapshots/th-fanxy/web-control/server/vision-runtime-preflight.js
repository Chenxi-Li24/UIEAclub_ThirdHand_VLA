'use strict';

const fs = require('fs');
const path = require('path');

function defaultEvidencePaths(projectRoot = path.resolve(__dirname, '../..')) {
  const root = path.resolve(projectRoot);
  const evidenceDir = path.join(root, 'data/calibration/active-view-foundation');
  return Object.freeze({
    evidenceDir,
    cameraEvidence: path.join(evidenceDir, 'camera.json'),
    tableEvidence: path.join(evidenceDir, 'table.json'),
    catalogEvidence: path.join(evidenceDir, 'observation-catalog.json'),
  });
}

function isReadableFile(filePath, exists = fs.existsSync) {
  return typeof filePath === 'string' && path.isAbsolute(filePath) && exists(filePath);
}

function evaluateVisionRuntimePreflight({
  onlineEnabled,
  evidenceDir,
  cameraEvidence,
  tableEvidence,
  catalogEvidence,
  exists = fs.existsSync,
}) {
  const evidencePaths = Object.freeze({
    evidenceDir: path.resolve(evidenceDir),
    cameraEvidence: path.resolve(cameraEvidence),
    tableEvidence: path.resolve(tableEvidence),
    catalogEvidence: path.resolve(catalogEvidence),
  });
  const blockers = [];
  if (onlineEnabled !== true) blockers.push('vision_online_disabled');
  if (!isReadableFile(evidencePaths.cameraEvidence, exists)) {
    blockers.push('camera_evidence_missing');
  }
  if (!isReadableFile(evidencePaths.tableEvidence, exists)) {
    blockers.push('table_evidence_missing');
  }
  const foundationReady = onlineEnabled === true &&
    !blockers.includes('camera_evidence_missing') &&
    !blockers.includes('table_evidence_missing');
  if (!isReadableFile(evidencePaths.catalogEvidence, exists)) {
    blockers.push('observation_catalog_missing');
  }
  const motionEvidenceReady = foundationReady &&
    !blockers.includes('observation_catalog_missing');
  return Object.freeze({
    perceptionReady: foundationReady,
    activeViewReady: motionEvidenceReady,
    graspReady: motionEvidenceReady,
    evidencePaths,
    blockers: Object.freeze(blockers),
  });
}

module.exports = {
  defaultEvidencePaths,
  evaluateVisionRuntimePreflight,
};
