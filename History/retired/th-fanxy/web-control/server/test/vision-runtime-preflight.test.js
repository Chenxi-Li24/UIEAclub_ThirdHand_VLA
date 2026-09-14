'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const {
  defaultEvidencePaths,
  evaluateVisionRuntimePreflight,
} = require('../vision-runtime-preflight');
const { CameraBridge } = require('../camera-bridge');

function touch(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, '{}\n', 'utf8');
}

const temporaryRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'vision-preflight-'));
try {
  const defaults = defaultEvidencePaths(temporaryRoot);
  assert.deepEqual(defaults, {
    evidenceDir: path.join(temporaryRoot, 'data/calibration/active-view-foundation'),
    cameraEvidence: path.join(
      temporaryRoot,
      'data/calibration/active-view-foundation/camera.json'
    ),
    tableEvidence: path.join(
      temporaryRoot,
      'data/calibration/active-view-foundation/table.json'
    ),
    catalogEvidence: path.join(
      temporaryRoot,
      'data/calibration/active-view-foundation/observation-catalog.json'
    ),
  });

  touch(defaults.cameraEvidence);
  touch(defaults.tableEvidence);
  const foundationOnly = evaluateVisionRuntimePreflight({
    onlineEnabled: true,
    ...defaults,
  });
  assert.equal(foundationOnly.perceptionReady, true);
  assert.equal(foundationOnly.activeViewReady, false);
  assert.equal(foundationOnly.graspReady, false);
  assert.deepEqual(foundationOnly.blockers, ['observation_catalog_missing']);
  assert.equal(Object.isFrozen(foundationOnly), true);
  assert.equal(Object.isFrozen(foundationOnly.evidencePaths), true);

  touch(defaults.catalogEvidence);
  const complete = evaluateVisionRuntimePreflight({ onlineEnabled: true, ...defaults });
  assert.equal(complete.perceptionReady, true);
  assert.equal(complete.activeViewReady, true);
  assert.equal(complete.graspReady, true);
  assert.deepEqual(complete.blockers, []);

  fs.unlinkSync(defaults.cameraEvidence);
  const missingCamera = evaluateVisionRuntimePreflight({
    onlineEnabled: true,
    ...defaults,
  });
  assert.equal(missingCamera.perceptionReady, false);
  assert.equal(missingCamera.activeViewReady, false);
  assert.equal(missingCamera.graspReady, false);
  assert.deepEqual(missingCamera.blockers, ['camera_evidence_missing']);

  const disabled = evaluateVisionRuntimePreflight({
    onlineEnabled: false,
    ...defaults,
  });
  assert.equal(disabled.perceptionReady, false);
  assert.equal(disabled.activeViewReady, false);
  assert.equal(disabled.graspReady, false);
  assert.deepEqual(disabled.blockers, ['vision_online_disabled', 'camera_evidence_missing']);

  const configProbe = spawnSync(
    process.execPath,
    ['-e', "process.stdout.write(JSON.stringify(require('./config').camera))"],
    {
      cwd: path.resolve(__dirname, '..'),
      encoding: 'utf8',
      env: {
        ...process.env,
        ACTIVE_VIEW_EVIDENCE_DIR: '',
        ACTIVE_VIEW_CAMERA_EVIDENCE: '',
        ACTIVE_VIEW_TABLE_EVIDENCE: '',
        ACTIVE_VIEW_CATALOG: '',
      },
    }
  );
  assert.equal(configProbe.status, 0, configProbe.stderr);
  const cameraConfig = JSON.parse(configProbe.stdout);
  const repositoryEvidence = path.resolve(
    __dirname,
    '../../../data/calibration/active-view-foundation'
  );
  assert.equal(cameraConfig.activeViewEvidenceDir, repositoryEvidence);
  assert.equal(cameraConfig.activeViewCameraEvidence, path.join(repositoryEvidence, 'camera.json'));
  assert.equal(cameraConfig.activeViewTableEvidence, path.join(repositoryEvidence, 'table.json'));
  assert.equal(
    cameraConfig.activeViewCatalog,
    path.join(repositoryEvidence, 'observation-catalog.json')
  );
  assert.equal(
    cameraConfig.graspPreviewConfig,
    path.resolve(__dirname, '../../../configs/vision/grasp_preview.yaml')
  );

  const fallbackSpec = new CameraBridge({ onlineEnabled: true }).buildSpawnSpec();
  assert.equal(fallbackSpec.env.ACTIVE_VIEW_EVIDENCE_DIR, repositoryEvidence);
  assert.equal(
    fallbackSpec.env.ACTIVE_VIEW_CATALOG,
    path.join(repositoryEvidence, 'observation-catalog.json')
  );
  assert.equal(
    fallbackSpec.env.GRASP_PREVIEW_CONFIG,
    path.resolve(__dirname, '../../../configs/vision/grasp_preview.yaml')
  );

  const launcher = fs.readFileSync(
    path.resolve(__dirname, '../../../scripts/vision/start_dual_camera_online.sh'),
    'utf8'
  );
  assert.match(launcher, /data\/calibration\/active-view-foundation/);
  assert.match(launcher, /ACTIVE_VIEW_CAMERA_EVIDENCE=/);
  assert.match(launcher, /ACTIVE_VIEW_TABLE_EVIDENCE=/);
  assert.match(launcher, /ACTIVE_VIEW_CATALOG=/);
  assert.match(launcher, /GRASP_EXECUTION_ENABLED=0/);

  console.log('PASS vision runtime preflight separates perception and motion evidence gates');
} finally {
  fs.rmSync(temporaryRoot, { recursive: true, force: true });
}
