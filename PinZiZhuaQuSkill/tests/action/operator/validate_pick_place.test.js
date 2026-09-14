'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  buildActionEvidence,
} = require('../../../src/thirdhand_va/action/evidence/action_evidence');
const {
  evaluateCoverage, loadCalibration, loadSpecimenManifest, main,
} = require('../../../scripts/action/validate_pick_place');

const IDS = Object.freeze({
  action: `sha256:${'a'.repeat(64)}`,
  vision: `sha256:${'b'.repeat(64)}`,
  calibration: `sha256:${'c'.repeat(64)}`,
  path: `sha256:${'d'.repeat(64)}`,
  grounding: `sha256:${'e'.repeat(64)}`,
  sam: `sha256:${'f'.repeat(64)}`,
  specimens: `sha256:${'9'.repeat(64)}`,
});
const MODELS = Object.freeze([
  Object.freeze({
    model_id: 'IDEA-Research/grounding-dino-tiny', revision: '1'.repeat(40),
    weights_sha256: IDS.grounding,
  }),
  Object.freeze({
    model_id: 'facebook/sam2.1-hiera-tiny', revision: '2'.repeat(40),
    weights_sha256: IDS.sam,
  }),
]);
const MODEL_PROVENANCE = Object.freeze({
  vision_config_id: IDS.vision,
  camera_registration_id: 'lumos-registration-v1',
  camera_mount_id: 'wrist-mount-v1',
  grounding_model: MODELS[0].model_id,
  grounding_revision: MODELS[0].revision,
  grounding_weights_sha256: IDS.grounding,
  sam_model: MODELS[1].model_id,
  sam_revision: MODELS[1].revision,
  sam_weights_sha256: IDS.sam,
});

function actionEvidence(requestId = 'trial-1', targetId = 2) {
  return buildActionEvidence({
    stableId: targetId,
    requestId,
    motionEpoch: 2,
    sourceVisionEvidenceIds: [1, 2, 3].map(value => `sha256:${String(value).repeat(64)}`),
    sourcePreviewIds: [4, 5, 6].map(value => `sha256:${String(value).repeat(64)}`),
    sourceArmStateIds: [7, 8, 9].map(value => `sha256:${String(value).repeat(64)}`),
    sourceObservedAtMs: [1000, 1010, 1020],
    calibrationId: IDS.calibration,
    visionConfigId: IDS.vision,
    actionConfigId: IDS.action,
    pathValidationId: IDS.path,
    modelProvenance: MODEL_PROVENANCE,
    detectedGraspPointM: [0.4, -0.1, 0.12],
    commandedFlangeGraspM: [0.4475, -0.09, 0.12],
    flangeOffsetBaseM: [0.0475, 0.01, 0],
    baseSpreadM: 0.002,
    posePositionStdM: [0.001, 0.001, 0.002],
    widthM: 0.05,
    eulerRad: [0, Math.PI / 2, 0],
  });
}

function dependencies(overrides = {}) {
  return {
    env: {
      THIRDHAND_LIVE_TEST: '1',
      THIRDHAND_ALLOW_ROBOT: 'I_ACCEPT_SUPERVISED_ROBOT_MOTION',
    },
    loadActionConfig: () => ({
      execution_enabled: true,
      content_id: IDS.action,
      grasp: { offset_validated: true, flange_offset_base_m: [0.0475, 0.01, 0] },
      place: {
        strategy: 'fixed_xy_keep_grasp_z', validated: true,
        fixed_xy_m: [0.2678, 0.0107], grasp_z_range_m: [0.08, 0.30],
        vertical_clearance_m: 0.10, path_validation_id: IDS.path,
      },
    }),
    loadCalibration: () => ({
      numerically_validated: true,
      physically_validated: true,
      approved_for_bottle_grasp: true,
      camera_serial: '250801DR48FP25002738',
      registration_id: 'lumos-registration-v1',
      camera_mount_id: 'wrist-mount-v1',
      calibration_id: IDS.calibration,
    }),
    loadVisionEvidence: () => ({
      vision_config_id: IDS.vision,
      camera_serial: '250801DR48FP25002738',
      registration_id: 'lumos-registration-v1',
      camera_mount_id: 'wrist-mount-v1',
      models: MODELS,
    }),
    loadSpecimenManifest: () => ({
      content_id: IDS.specimens,
      specimens: ['opaque-a', 'opaque-b', 'opaque-c', 'opaque-d', 'opaque-e'],
    }),
    hashFile: file => file.includes('action') ? IDS.action
      : file.includes('vision') ? IDS.vision : IDS.calibration,
    idFactory: () => 'trial-1',
    delay: async () => {},
    beforeTrial: async () => ({
      approved: true, specimenId: 'opaque-a', positionLabel: 'grid-a1',
    }),
    confirmTrial: async () => ({ upright: true, wrongPick: false, idSwitch: false }),
    write: () => {},
    writeError: () => {},
    now: () => new Date('2026-08-23T00:00:00.000Z'),
    ...overrides,
  };
}

function health() {
  return {
    camera_ready: true,
    robot_control_enabled: true,
    artifacts: {
      action_config_id: IDS.action,
      path_validation_id: IDS.path,
      calibration_id: IDS.calibration,
      vision_config_id: IDS.vision,
      camera_serial: '250801DR48FP25002738',
      registration_id: 'lumos-registration-v1',
      camera_mount_id: 'wrist-mount-v1',
      model_provenance: MODEL_PROVENANCE,
    },
  };
}

function completedResult(requestId = 'trial-1', targetId = 2) {
  const evidence = actionEvidence(requestId, targetId);
  return {
    ok: true, phase: 'complete', targetId, requestId,
    evidenceId: evidence.id, actionEvidence: evidence,
  };
}

test('hardware validator help is side-effect free', async () => {
  const lines = [];
  let networkCalls = 0;
  const code = await main(['--help'], {
    env: {},
    fetchImpl: async () => { networkCalls += 1; throw new Error('must not run'); },
    write: line => lines.push(line),
    writeError: () => {},
  });

  assert.equal(code, 0);
  assert.equal(networkCalls, 0);
  assert.match(lines.join('\n'), /--allow-robot/);
});

test('hardware validator refuses without both exact authorization gates', async () => {
  let networkCalls = 0;
  const code = await main(['--trials', '1'], {
    env: {},
    fetchImpl: async () => { networkCalls += 1; throw new Error('must not run'); },
    write: () => {},
    writeError: () => {},
  });

  assert.equal(code, 2);
  assert.equal(networkCalls, 0);
});

test('hardware validator refuses inactive config before network access', async () => {
  let networkCalls = 0;
  const code = await main([
    '--allow-robot', '--trials', '1', '--calibration', 'handeye.json',
    '--specimens', 'specimens.json',
  ], dependencies({
    loadActionConfig: () => ({
      execution_enabled: false,
      content_id: IDS.action,
      grasp: { offset_validated: false },
      place: { validated: false, fixed_xy_m: [0.2678, 0.0107], path_validation_id: null },
    }),
    fetchImpl: async () => { networkCalls += 1; throw new Error('must not run'); },
  }));

  assert.equal(code, 2);
  assert.equal(networkCalls, 0);
});

test('validator calibration loader enforces explicit flange transform and hard 10 mm limit', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'va-calibration-'));
  const file = path.join(directory, 'handeye.json');
  const payload = {
    schema: 'thirdhand-handeye-calibration-v3',
    robot_state_semantics: 'T_base_flange',
    extrinsic_semantics: 'T_flange_camera',
    T_flange_camera: { matrix_4x4: [
      [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
    ] },
    camera: {
      camera_serial: 'camera', registration_id: 'registration',
      camera_mount_id: 'mount',
    },
    numerically_validated: true,
    camera_mount_id_activation: true,
    activated_camera_mount_id: 'mount',
    approved_for_bottle_grasp: true,
    physical_validation: {
      status: 'passed', measured_error_m: 0.009,
      required_3d_point_or_grasp_error_m_max: 0.011,
    },
  };
  fs.writeFileSync(file, JSON.stringify(payload));
  assert.equal(loadCalibration(file).approved_for_bottle_grasp, false);
  payload.physical_validation.required_3d_point_or_grasp_error_m_max = 0.010;
  payload.T_flange_camera.matrix_4x4[0][0] = 2;
  fs.writeFileSync(file, JSON.stringify(payload));
  assert.equal(loadCalibration(file).approved_for_bottle_grasp, false);
  payload.T_flange_camera.matrix_4x4[0][0] = 1;
  fs.writeFileSync(file, JSON.stringify(payload));
  assert.equal(loadCalibration(file).approved_for_bottle_grasp, true);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('specimen manifest pre-registers five case-insensitively unique physical IDs', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'va-specimens-'));
  const file = path.join(directory, 'specimens.json');
  const payload = {
    schema: 'thirdhand-va-bottle-specimens-v1',
    specimens: ['opaque-a', 'opaque-b', 'opaque-c', 'opaque-d', 'opaque-e'].map(
      specimen_id => ({ specimen_id, description: `labelled ${specimen_id}` })
    ),
  };
  fs.writeFileSync(file, JSON.stringify(payload));
  const loaded = loadSpecimenManifest(file);
  assert.deepEqual(loaded.specimens, [
    'opaque-a', 'opaque-b', 'opaque-c', 'opaque-d', 'opaque-e',
  ]);
  payload.specimens[4].specimen_id = 'OPAQUE-A';
  fs.writeFileSync(file, JSON.stringify(payload));
  assert.throws(() => loadSpecimenManifest(file), /specimen IDs.*unique/);
  fs.rmSync(directory, { recursive: true, force: true });
});

test('authorized validator uses only loopback API and records bound action evidence', async () => {
  const calls = [];
  let report;
  let statusReads = 0;
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith('/health')) return response(200, health());
    if (url.endsWith('/api/va/start')) return response(202, {
      accepted: true, request_id: 'trial-1', target_id: 2,
      robot_control_enabled: true,
    });
    statusReads += 1;
    return response(200, statusReads === 1 ? { active: true } : {
      active: false, last_result: completedResult(),
    });
  };
  const code = await main([
    '--allow-robot', '--trials', '1', '--target-id', '2',
    '--config', 'action.yaml', '--vision-config', 'vision.yaml',
    '--calibration', 'handeye.json', '--specimens', 'specimens.json',
  ], dependencies({
    fetchImpl,
    writeReport: (_path, value) => { report = structuredClone(value); },
  }));

  assert.equal(code, 0);
  assert.equal(report.passed, true);
  assert.equal(report.trials[0].target_id, 2);
  assert.equal(report.acceptance.invalid_evidence_authorization_count, 0);
  assert.equal(report.evidence.models[0].weights_sha256, IDS.grounding);
  assert.equal(report.evidence.specimen_manifest_sha256, IDS.specimens);
  assert.deepEqual(calls.map(item => new URL(item.url).pathname), [
    '/health', '/api/va/start', '/api/va/status', '/api/va/status',
  ]);
  assert.equal(calls.some(item => item.url.startsWith('ws:')), false);
});

test('invalid terminal action evidence can never count as a successful trial', async () => {
  let report;
  const invalid = completedResult();
  invalid.actionEvidence = {
    ...invalid.actionEvidence,
    payload: { ...invalid.actionEvidence.payload, stable_id: 1 },
  };
  const fetchImpl = async url => {
    if (url.endsWith('/health')) return response(200, health());
    if (url.endsWith('/api/va/start')) return response(202, {
      accepted: true, request_id: 'trial-1', target_id: 2,
      robot_control_enabled: true,
    });
    return response(200, { active: false, last_result: invalid });
  };
  const code = await main([
    '--allow-robot', '--trials', '1', '--target-id', '2',
    '--config', 'action.yaml', '--vision-config', 'vision.yaml',
    '--calibration', 'handeye.json', '--specimens', 'specimens.json',
  ], dependencies({
    fetchImpl,
    writeReport: (_path, value) => { report = structuredClone(value); },
  }));

  assert.equal(code, 1);
  assert.equal(report.passed, false);
  assert.equal(report.acceptance.invalid_evidence_authorization_count, 1);
});

test('polling failure requests correlated stop, confirms inactivity, and aborts the run', async () => {
  const calls = [];
  let report;
  let statusReads = 0;
  const fetchImpl = async (url, options = {}) => {
    const route = new URL(url).pathname;
    calls.push({ route, options });
    if (route === '/health') return response(200, health());
    if (route === '/api/va/start') return response(202, {
      accepted: true, request_id: 'trial-1', target_id: 2,
      robot_control_enabled: true,
    });
    if (route === '/api/va/stop') return response(202, { accepted: true });
    statusReads += 1;
    if (statusReads === 1) throw new Error('network_lost');
    return response(200, { active: false, last_result: null });
  };
  const code = await main([
    '--allow-robot', '--trials', '2', '--target-id', '2',
    '--config', 'action.yaml', '--vision-config', 'vision.yaml',
    '--calibration', 'handeye.json', '--specimens', 'specimens.json',
  ], dependencies({
    fetchImpl,
    writeReport: (_path, value) => { report = structuredClone(value); },
  }));

  assert.equal(code, 1);
  assert.equal(report.trials.length, 1);
  assert.equal(report.trials[0].stop_confirmation.confirmed, true);
  assert.equal(calls.filter(call => call.route === '/api/va/start').length, 1);
  const stopBody = JSON.parse(calls.find(call => call.route === '/api/va/stop').options.body);
  assert.equal(stopBody.request_id, 'validator-stop:trial-1');
});

test('30-trial acceptance requires five registered specimens and spatially distinct placements', () => {
  const repeated = Array.from({ length: 30 }, (_, index) => ({
    specimen_id: 'opaque-a', position_label: `claimed-${index}`,
    evidence_authorized: true, measured_grasp_point_m: [0.4, 0.0, 0.2],
  }));
  const repeatedCoverage = evaluateCoverage(repeated, 30);
  assert.equal(repeatedCoverage.passed, false);
  assert.equal(repeatedCoverage.specimen_count, 1);
  assert.equal(repeatedCoverage.measured_position_count, 1);

  const covered = Array.from({ length: 30 }, (_, index) => ({
    specimen_id: `opaque-${index % 5}`,
    position_label: `grid-${index}`,
    evidence_authorized: true,
    measured_grasp_point_m: [0.2 + (index % 6) * 0.04,
      -0.16 + Math.floor(index / 6) * 0.04, 0.2],
  }));
  const coveredSummary = evaluateCoverage(covered, 30);
  assert.equal(coveredSummary.passed, true);
  assert.equal(coveredSummary.specimen_count, 5);
  assert.equal(coveredSummary.position_label_count, 30);
  assert.equal(coveredSummary.measured_position_count, 30);
});

function response(status, body) {
  return { status, async json() { return body; } };
}
