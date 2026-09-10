'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');

const {
  CameraBridge,
} = require('../../../src/thirdhand_va/action/adapters/camera_bridge');

const bridge = new CameraBridge({
  python: 'python-test',
});
const spec = bridge.buildSpawnSpec();
const projectRoot = path.resolve(__dirname, '../../..');

assert.equal(spec.cwd, projectRoot);
assert.deepEqual(spec.args, [
  '-u',
  '-m',
  'apps.bottle_pick.camera_bridge',
]);
assert.equal(
  spec.env.XVISIO_STREAM_EXECUTABLE,
  path.join(projectRoot, 'build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream')
);
assert.equal(
  spec.env.VISION_CONFIG,
  path.join(projectRoot, 'configs/vision.yaml')
);
assert.equal(Object.keys(spec.env).some(key => key.includes('D435')), false);
assert.equal(Object.keys(spec.env).some(key => key.includes('ACTIVE_VIEW')), false);

const calibratedBridge = new CameraBridge({
  python: 'python-test', projectRoot,
  calibrationFile: 'configs/calibration/lumos-handeye.pending.json',
});
assert.equal(
  calibratedBridge.buildSpawnSpec().env.THIRDHAND_VA_HANDEYE,
  path.join(projectRoot, 'configs/calibration/lumos-handeye.pending.json')
);

const sent = [];
bridge.child = {
  stdin: {
    destroyed: false,
    writable: true,
    writableEnded: false,
    write: value => { sent.push(JSON.parse(value)); return true; },
  },
};
assert.equal(bridge.send({
  type: 'select_bottle', stable_id: 2, request_id: 'req-2',
}), true);
assert.equal(bridge.send({
  type: 'select_bottle', side: 'left', ordinal: 2, request_id: 'legacy',
}), false);
assert.equal(bridge.send({
  type: 'reset_target_pose_reference', request_id: 'req-2', motion_epoch: 4,
}), true);
assert.equal(bridge.send({
  type: 'release_bottle', request_id: 'req-2',
}), true);
assert.deepEqual(sent.map(item => item.type), [
  'select_bottle', 'reset_target_pose_reference', 'release_bottle',
]);
assert.equal(bridge.sendArmState(
  [0.4, 0, 0.2], [0, 0, 0], [0, 1, 2, 3, 4, 5], [0, 0, 0, 0, 0, 0],
  true, 1000,
), true);
assert.deepEqual(sent.at(-1), {
  type: 'arm_state',
  pose_frame: 'robot_flange',
  flange_position_m: [0.4, 0, 0.2],
  flange_euler_rad: [0, 0, 0],
  joints_deg: [0, 1, 2, 3, 4, 5],
  velocities_deg_s: [0, 0, 0, 0, 0, 0],
  stationary: true,
  observed_monotonic_ns: 1000,
});

const modelProvenance = {
  vision_config_id: `sha256:${'a'.repeat(64)}`,
  camera_registration_id: 'registration-1',
  camera_mount_id: 'mount-1',
  grounding_model: 'debug/grounding',
  grounding_revision: '1'.repeat(40),
  grounding_weights_sha256: `sha256:${'b'.repeat(64)}`,
  sam_model: 'debug/sam',
  sam_revision: '2'.repeat(40),
  sam_weights_sha256: `sha256:${'c'.repeat(64)}`,
};
bridge._handleLine(JSON.stringify({
  type: 'bridge_ready', camera_serial: 'camera-1',
  registration_id: 'registration-1', camera_mount_id: 'mount-1',
  vision_config_id: modelProvenance.vision_config_id,
  calibration_id: `sha256:${'d'.repeat(64)}`,
  calibration_approved: true, model_provenance: modelProvenance,
}));
const detections = [];
const rejected = [];
bridge.on('detection_result', message => detections.push(message));
bridge.on('detection_rejected', message => rejected.push(message));
const detection = {
  type: 'detection_result', schema: 'thirdhand-va-detection-v3',
  frame_id: 1, monotonic_ns: 1000, ts: 10,
  camera_serial: 'camera-1', registration_id: 'registration-1',
  model_provenance: modelProvenance,
  targets: [{
    grasp_preview: {
      calibration_id: `sha256:${'d'.repeat(64)}`,
      vision_config_id: modelProvenance.vision_config_id,
      model_provenance: modelProvenance,
    },
  }],
};
bridge._handleLine(JSON.stringify(detection));
bridge._handleLine(JSON.stringify({
  ...detection, frame_id: 2,
  model_provenance: { ...modelProvenance, grounding_revision: '3'.repeat(40) },
}));
bridge._handleLine(JSON.stringify({
  ...detection, frame_id: 3,
  targets: [{
    grasp_preview: {
      ...detection.targets[0].grasp_preview,
      calibration_id: `sha256:${'e'.repeat(64)}`,
    },
  }],
}));
assert.equal(detections.length, 1);
assert.equal(rejected.length, 2);
assert.equal(bridge.getInfo().ready, true);

console.log('camera bridge spawn smoke: ok');
