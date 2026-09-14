'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { RobotClient } = require(
  '../../../src/thirdhand_va/action/adapters/robot_client'
);
const { VisionClient } = require(
  '../../../src/thirdhand_va/action/adapters/vision_client'
);

test('robot client sends only explicitly supported commands', () => {
  const sent = [];
  const client = new RobotClient({
    transport: command => { sent.push(command); return true; },
  });

  assert.equal(client.send({ cmd: 'move_l', position: [0.4, 0, 0.2] }), true);
  assert.equal(client.send({ cmd: 'execute_grasp', target_id: 2 }), false);
  assert.equal(client.send({ cmd: 'shell', value: 'unsafe' }), false);
  assert.deepEqual(sent, [{ cmd: 'move_l', position: [0.4, 0, 0.2] }]);
});

test('vision client emits only fail-closed versioned results', () => {
  const client = new VisionClient();
  const received = [];
  client.on('result', result => received.push(result));

  assert.equal(client.accept({ schema: 'unknown', frame_id: 1 }), false);
  assert.equal(client.accept({
    schema: 'thirdhand-va-detection-v3',
    frame_id: 7,
    status: 'ready',
    robot_control_enabled: true,
    reasons: [],
    targets: [],
  }), false);
  const valid = {
    type: 'detection_result',
    schema: 'thirdhand-va-detection-v3',
    frame_id: 7,
    monotonic_ns: 700,
    request_id: 'req-2',
    selected_stable_id: 2,
    camera_serial: '250801DR48FP25002738',
    registration_id: 'xvisio-sdk:250801DR48FP25002738',
    model_provenance: {
      vision_config_id: `sha256:${'f'.repeat(64)}`,
      camera_registration_id: 'xvisio-sdk:250801DR48FP25002738',
      camera_mount_id: 'lumos-ego-std:end-effector:installation-1',
      grounding_model: 'fixture/dino', grounding_revision: 'a'.repeat(40),
      grounding_weights_sha256: `sha256:${'b'.repeat(64)}`,
      sam_model: 'fixture/sam', sam_revision: 'c'.repeat(40),
      sam_weights_sha256: `sha256:${'d'.repeat(64)}`,
    },
    motion_epoch: 3,
    evidence_id: `sha256:${'a'.repeat(64)}`,
    status: 'ready',
    robot_control_enabled: false,
    reasons: [],
    stable_hits: 4,
    window_size: 5,
    pose: {
      frame: 'xvisio_color', point_m: [0.1, 0.0, 0.4],
      axis: [0, 1, 0], approach: [0, 0, 1], width_m: 0.06,
      position_std_m: [0.001, 0.001, 0.002], depth_valid_ratio: 0.9,
    },
    targets: [{
      stable_id: 2, backend_track_id: 91, track_state: 'confirmed',
      detection_id: 77, label: 'bottle', score: 0.9,
      bbox_xyxy: [1, 2, 8, 20], centroid_xy: [4.5, 11],
      selected: true, depth_valid: true, blockers: [],
    }],
  };
  assert.equal(client.accept(valid), true);
  assert.equal(received.length, 1);
  assert.equal(received[0].frameId, 7);
  assert.equal(received[0].selectedStableId, 2);
  assert.equal(received[0].targets[0].stableId, 2);
  assert.equal(Object.isFrozen(received[0]), true);
  assert.equal(client.accept({
    ...valid,
    targets: [...valid.targets, {...valid.targets[0], detection_id: 78}],
  }), false);
  assert.equal(client.accept({...valid, evidence_id: 'not-a-hash'}), false);
});
