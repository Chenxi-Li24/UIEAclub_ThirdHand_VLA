'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { loadActionConfig } = require('../../src/thirdhand_va/action/config');

test('real config uses commissioned home outside stop margin and remains inactive', () => {
  const config = loadActionConfig('configs/action.yaml');

  assert.equal(config.schema, 'thirdhand-action-config-v2');
  assert.equal(config.execution_enabled, false);
  assert.equal(config.robot.backend, 'startouch_process');
  assert.equal(config.robot.home_tolerance_deg, 0.5);
  assert.deepEqual(config.robot.presets.home, [
    -0.163927, -2.611904, -4.0, 33.058620, 0.338783, 0.185784,
  ]);
  assert.equal(config.robot.sdk_path, '/home/nieqingcao/arm/startouch_sdk');
  assert.equal(config.robot.runtime_root, path.resolve(
    'build/startouch_runtime/startouch_sdk'
  ));
  assert.equal(config.robot.source_manifest, path.resolve(
    'native/startouch/startouch_source.json'
  ));
  assert.equal(config.robot.safety_profile_id,
    'thirdhand-conservative-safety-v1');
  assert.equal(config.robot.safety_config_sha256,
    '4ca3953ea04c5558262bf16f6b659e84896d85ede7469165d4c428aae0b1ba20');
  assert.equal(config.robot.joint_limit_stop_margin_deg, 3.0);
  assert.deepEqual(config.robot.preset_stop_margin_violations, []);
  assert.equal(path.basename(config.robot.bridge_path), 'startouch_bridge.py');
  assert.deepEqual(config.grasp.flange_offset_base_m, [0.0475, 0.01, 0]);
  assert.equal(config.grasp.offset_validated, false);
  assert.equal(config.place.validated, false);
  assert.equal(config.place.path_validation_id, null);
  assert.equal(config.place.startup_home_validated, false);
  assert.equal(config.place.startup_joint_ranges_deg, null);
  assert.equal(config.place.strategy, 'fixed_xy_keep_grasp_z');
  assert.deepEqual(config.place.fixed_xy_m, [
    0.282831634, -0.591124195,
  ]);
  assert.deepEqual(config.place.euler_rad, [
    0.001938936, -0.075722729, -1.123057982,
  ]);
  assert.equal(config.place.vertical_clearance_m, 0.25);
  assert.deepEqual(config.motion.grasp_euler_rad, [
    0.052626251, -0.083733625, 0.492493650,
  ]);
  assert.equal(config.motion.lift_height_m, 0.25);
  assert.equal(config.motion.safe_transit_z_m, 0.306371896);
  assert.equal(config.gripper.execution_max_width_m, 0.072);
  assert.equal(Object.isFrozen(config), true);
  assert.equal(Object.isFrozen(config.motion), true);
});

test('strict loader rejects unknown keys and activation with an unvalidated grasp offset', t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-action-config-'));
  t.after(() => fs.rmSync(temp, { recursive: true }));
  const original = fs.readFileSync('configs/action.yaml', 'utf8');
  const unknown = path.join(temp, 'unknown.yaml');
  fs.writeFileSync(unknown, `${original}\nextra: true\n`);
  assert.throws(() => loadActionConfig(unknown), /unknown config key: extra/);

  const unsafe = path.join(temp, 'unsafe.yaml');
  fs.writeFileSync(unsafe, original.replace(
    'execution_enabled: false', 'execution_enabled: true'
  ));
  assert.throws(() => loadActionConfig(unsafe), /grasp_offset_not_validated/);
});

test('validated place requires offset approval and a finite grasp-Z range', t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-place-config-'));
  t.after(() => fs.rmSync(temp, { recursive: true }));
  const source = fs.readFileSync('configs/action.yaml', 'utf8')
    .replace('execution_enabled: false', 'execution_enabled: true')
    .replace('  validated: false', '  validated: true');
  const file = path.join(temp, 'missing-place.yaml');
  fs.writeFileSync(file, source);

  assert.throws(() => loadActionConfig(file), /grasp_z_range_m/);
});

test('activated dynamic path requires matching range-bound physical artifact', t => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-path-config-'));
  t.after(() => fs.rmSync(temp, { recursive: true }));
  const artifact = {
    schema: 'thirdhand-pick-place-path-validation-v2',
    physically_validated: true,
    approved_for_execution: true,
    fixed_xy_m: [0.282831634, -0.591124195],
    place_euler_rad: [0.001938936, -0.075722729, -1.123057982],
    grasp_z_range_m: [0.16, 0.28],
    vertical_clearance_m: 0.25,
    flange_offset_base_m: [0.0475, 0.0100, 0.0],
    euler_rad: [0.052626251, -0.083733625, 0.492493650],
    lift_height_m: 0.25,
    safe_transit_z_m: 0.306371896,
    linear_speed_m_s: 0.03,
    home_preset: 'home',
    home_joints_deg: [-0.163927, -2.611904, -4.0, 33.058620, 0.338783, 0.185784],
    home_tolerance_deg: 0.5,
    startup_home_validated: true,
    startup_joint_ranges_deg: [
      [-0.7, 0.4], [-3.2, 0.4], [-4.0, -3.1], [32.4, 33.7],
      [-0.2, 0.9], [-0.4, 0.8],
    ],
    source_observation_path_validation_id:
      'sha256:84dac966824f8e41ee8474534295576250618bc998dc61948a98705d7ec28572',
  };
  const artifactPath = path.join(temp, 'post-release.json');
  const artifactBytes = `${JSON.stringify(artifact, null, 2)}\n`;
  fs.writeFileSync(artifactPath, artifactBytes);
  const digest = `sha256:${require('node:crypto').createHash('sha256')
    .update(artifactBytes).digest('hex')}`;
  const source = fs.readFileSync('configs/action.yaml', 'utf8')
    .replace('execution_enabled: false', 'execution_enabled: true')
    .replace('offset_validated: false', 'offset_validated: true')
    .replace('validated: false', 'validated: true')
    .replace('grasp_z_range_m: null', 'grasp_z_range_m: [0.16, 0.28]')
    .replace('path_validation_file: null', 'path_validation_file: "post-release.json"')
    .replace('path_validation_sha256: null', `path_validation_sha256: "${digest}"`);
  const configPath = path.join(temp, 'action.yaml');
  fs.writeFileSync(configPath, source);

  const loaded = loadActionConfig(configPath);
  assert.equal(loaded.place.path_validation_id, digest);
  assert.equal(loaded.place.startup_home_validated, true);
  assert.deepEqual(loaded.place.startup_joint_ranges_deg, [
    [-0.7, 0.4], [-3.2, 0.4], [-4.0, -3.1], [32.4, 33.7],
    [-0.2, 0.9], [-0.4, 0.8],
  ]);
  assert.deepEqual(loaded.place.grasp_z_range_m, [0.16, 0.28]);

  const unsafeHome = [-0.163927, -2.611904, -0.579209,
    33.058620, 0.338783, 0.185784];
  const unsafeHomeArtifact = {
    ...artifact,
    home_joints_deg: unsafeHome,
    startup_joint_ranges_deg: [
      [-0.7, 0.4], [-3.2, 0.4], [-1.1, -0.1], [32.4, 33.7],
      [-0.2, 0.9], [-0.4, 0.8],
    ],
  };
  const unsafeHomeBytes = `${JSON.stringify(unsafeHomeArtifact, null, 2)}\n`;
  fs.writeFileSync(artifactPath, unsafeHomeBytes);
  const unsafeHomeDigest = `sha256:${require('node:crypto').createHash('sha256')
    .update(unsafeHomeBytes).digest('hex')}`;
  fs.writeFileSync(configPath, source
    .replace(digest, unsafeHomeDigest)
    .replace(
      'home: [-0.163927, -2.611904, -4.000000, 33.058620, 0.338783, 0.185784]',
      'home: [-0.163927, -2.611904, -0.579209, 33.058620, 0.338783, 0.185784]'
    ));
  assert.throws(
    () => loadActionConfig(configPath),
    /robot_preset_inside_joint_stop_margin:home:joint_3/
  );

  for (const changed of [
    { ...artifact, fixed_xy_m: [0.30, 0.01] },
    { ...artifact, place_euler_rad: [0, 0, 0.1] },
    { ...artifact, grasp_z_range_m: [0.15, 0.28] },
    { ...artifact, vertical_clearance_m: 0.12 },
    { ...artifact, lift_height_m: 0.20 },
    { ...artifact, safe_transit_z_m: 0.31 },
    { ...artifact, flange_offset_base_m: [0.04, 0.01, 0] },
    { ...artifact, euler_rad: [0, 0, 0.1] },
    { ...artifact, home_preset: 'other' },
    { ...artifact, home_joints_deg: [0, 0, 0, 0, 0, 1] },
    { ...artifact, home_tolerance_deg: 1.0 },
    { ...artifact, startup_home_validated: false },
    { ...artifact, source_observation_path_validation_id: `sha256:${'f'.repeat(64)}` },
  ]) {
    const changedBytes = `${JSON.stringify(changed, null, 2)}\n`;
    fs.writeFileSync(artifactPath, changedBytes);
    const changedDigest = `sha256:${require('node:crypto').createHash('sha256')
      .update(changedBytes).digest('hex')}`;
    fs.writeFileSync(configPath, source.replace(digest, changedDigest));
    assert.throws(
      () => loadActionConfig(configPath),
      /path validation artifact does not match executable path/
    );
  }

  const wrongSpeed = { ...artifact, linear_speed_m_s: 0.04 };
  const wrongSpeedBytes = `${JSON.stringify(wrongSpeed, null, 2)}\n`;
  fs.writeFileSync(artifactPath, wrongSpeedBytes);
  const wrongSpeedDigest = `sha256:${require('node:crypto').createHash('sha256')
    .update(wrongSpeedBytes).digest('hex')}`;
  fs.writeFileSync(configPath, source.replace(digest, wrongSpeedDigest));
  assert.throws(
    () => loadActionConfig(configPath),
    /path validation artifact does not match executable path/
  );

  fs.writeFileSync(configPath, source);
  fs.appendFileSync(artifactPath, ' ');
  assert.throws(() => loadActionConfig(configPath), /path validation hash mismatch/);
});
