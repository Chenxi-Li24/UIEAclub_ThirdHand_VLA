'use strict';

const assert = require('node:assert/strict');
const http = require('node:http');
const test = require('node:test');

const {
  createWebServer, homeRuntimeStatus, robotRuntimeReady, validateRuntimeAuthorization,
} = require('../../apps/bottle_pick/web_server');

function request({ port, method = 'GET', path = '/', body = null }) {
  return new Promise((resolve, reject) => {
    const encoded = body === null ? null : Buffer.from(JSON.stringify(body));
    const req = http.request({
      hostname: '127.0.0.1', port, method, path,
      headers: encoded === null ? {} : {
        'content-type': 'application/json', 'content-length': encoded.length,
      },
    }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({
        status: response.statusCode,
        body: JSON.parse(Buffer.concat(chunks).toString('utf8')),
      }));
    });
    req.on('error', reject);
    if (encoded !== null) req.write(encoded);
    req.end();
  });
}

test('web server exposes fail-closed health, status, and camera routes', async () => {
  const operator = {
    start() { return { accepted: false, reason: 'robot_execution_disabled' }; },
    stop() { return { accepted: true }; },
    snapshot() {
      return { schema: 'thirdhand.va.status.v1', active: false, last_result: null };
    },
  };
  const app = createWebServer({
    host: '127.0.0.1', port: 0, operatorController: operator,
    cameraBridge: { ready: false, subscribeMjpeg() { return false; } },
  });
  const address = await app.start();
  try {
    const health = await request({ port: address.port, path: '/health' });
    assert.deepEqual(health.body, {
      status: 'ok', camera_ready: false, va_active: false,
      robot_control_enabled: false, home: null, artifacts: {},
    });
    const status = await request({ port: address.port, path: '/api/va/status' });
    assert.equal(status.body.schema, 'thirdhand.va.status.v1');
    assert.equal(status.body.home, null);
    const stream = await request({
      port: address.port, path: '/camera_lumos_vision',
    });
    assert.equal(stream.status, 503);
    assert.equal(stream.body.reason, 'camera_not_ready');
    const legacy = await request({
      port: address.port, method: 'POST', path: '/api/vision/select',
      body: { side: 'left', ordinal: 2 },
    });
    assert.equal(legacy.status, 404);
  } finally {
    await app.stop();
  }
});

test('health exposes robot control only after a fresh healthy robot state', async () => {
  let ready = false;
  const operator = {
    start() { return { accepted: false, reason: 'robot_not_ready' }; },
    stop() { return { accepted: true }; },
    snapshot() { return { active: false }; },
  };
  const app = createWebServer({
    host: '127.0.0.1', port: 0, operatorController: operator,
    cameraBridge: { ready: true, subscribeMjpeg() { return false; } },
    robotControlEnabled: true,
    robotReady: () => ready,
    homeStatus: () => ({ phase: ready ? 'ready' : 'homing', ready }),
  });
  const address = await app.start();
  try {
    const blocked = await request({ port: address.port, path: '/health' });
    assert.equal(blocked.body.robot_control_enabled, false);
    assert.equal(blocked.body.home.phase, 'homing');
    ready = true;
    const allowed = await request({ port: address.port, path: '/health' });
    assert.equal(allowed.body.robot_control_enabled, true);
    assert.equal(allowed.body.home.phase, 'ready');
  } finally {
    await app.stop();
  }
});

test('live process assembly requires explicit camera, handeye, and robot authorization', () => {
  assert.throws(
    () => validateRuntimeAuthorization({ THIRDHAND_VA_ENABLE_CAMERA: '1' }),
    /camera enable requires THIRDHAND_VA_ALLOW_CAMERA=1/,
  );
  assert.throws(
    () => validateRuntimeAuthorization({
      THIRDHAND_VA_ENABLE_ROBOT: '1',
      THIRDHAND_ALLOW_ROBOT: 'I_ACCEPT_SUPERVISED_ROBOT_MOTION',
    }),
    /robot enable requires the camera bridge/,
  );
  assert.throws(
    () => validateRuntimeAuthorization({
      THIRDHAND_VA_ENABLE_CAMERA: '1', THIRDHAND_VA_ALLOW_CAMERA: '1',
      THIRDHAND_VA_ENABLE_ROBOT: '1',
      THIRDHAND_ALLOW_ROBOT: 'I_ACCEPT_SUPERVISED_ROBOT_MOTION',
    }),
    /robot enable requires THIRDHAND_VA_HANDEYE/,
  );
  assert.deepEqual(validateRuntimeAuthorization({
    THIRDHAND_VA_ENABLE_CAMERA: '1', THIRDHAND_VA_ALLOW_CAMERA: '1',
    THIRDHAND_VA_ENABLE_ROBOT: '1',
    THIRDHAND_VA_HANDEYE: '/approved/handeye.json',
    THIRDHAND_ALLOW_ROBOT: 'I_ACCEPT_SUPERVISED_ROBOT_MOTION',
  }), { cameraEnabled: true, robotEnabled: true });
  assert.deepEqual(validateRuntimeAuthorization({
    THIRDHAND_VA_VISION_WS_URL: 'ws://127.0.0.1:3100/ws',
  }), { cameraEnabled: true, robotEnabled: false });
});

test('robot readiness requires explicit flange state and matching approved artifacts', () => {
  const runtime = {
    camera_serial: 'camera', registration_id: 'registration', camera_mount_id: 'mount',
    vision_config_id: `sha256:${'a'.repeat(64)}`,
    calibration_id: `sha256:${'b'.repeat(64)}`,
    calibration_approved: true,
    model_provenance: {
      vision_config_id: `sha256:${'a'.repeat(64)}`,
      camera_registration_id: 'registration', camera_mount_id: 'mount',
      grounding_model: 'debug/grounding', grounding_revision: '1'.repeat(40),
      grounding_weights_sha256: `sha256:${'c'.repeat(64)}`,
      sam_model: 'debug/sam', sam_revision: '2'.repeat(40),
      sam_weights_sha256: `sha256:${'d'.repeat(64)}`,
    },
  };
  const state = {
    connected: true, healthy: true, stateFresh: true, stationary: true,
    poseFrame: 'robot_flange', jointsDeg: [0, 15, -30, 5, 0, 0],
  };
  const robotClient = {
    connected: true, protocolReady: true, getRobotState: () => state,
  };
  const cameraInfo = {
    ready: true, calibrationApproved: true, runtimeEvidence: runtime,
  };
  const config = {
    robot: {
      presets: { home: [0, 15, -30, 5, 0, 0] }, home_tolerance_deg: 0.5,
    },
    place: { home_preset: 'home' },
  };
  const homeCoordinator = { ready: true };

  assert.equal(robotRuntimeReady({
    robotClient, cameraInfo, approvedRuntimeEvidence: structuredClone(runtime),
    config, homeCoordinator,
  }), true);
  homeCoordinator.ready = false;
  assert.equal(robotRuntimeReady({
    robotClient, cameraInfo, approvedRuntimeEvidence: structuredClone(runtime),
    config, homeCoordinator,
  }), false);
  homeCoordinator.ready = true;
  state.jointsDeg[5] = 0.6;
  assert.equal(robotRuntimeReady({
    robotClient, cameraInfo, approvedRuntimeEvidence: structuredClone(runtime),
    config, homeCoordinator,
  }), false);
  state.jointsDeg[5] = 0;
  delete state.poseFrame;
  assert.equal(robotRuntimeReady({
    robotClient, cameraInfo, approvedRuntimeEvidence: structuredClone(runtime),
    config, homeCoordinator,
  }), false);
});

test('Home status changes to away whenever live joints leave approved Home', () => {
  const state = {
    connected: true, healthy: true, stateFresh: true, stationary: true,
    jointsDeg: [0, 15, -30, 5, 0, 0],
  };
  const dependencies = {
    homeCoordinator: { snapshot: () => ({ phase: 'ready', ready: true, reason: null }) },
    robotClient: { getRobotState: () => state },
    config: {
      robot: {
        presets: { home: [0, 15, -30, 5, 0, 0] }, home_tolerance_deg: 0.5,
      },
      place: { home_preset: 'home' },
    },
  };

  assert.equal(homeRuntimeStatus(dependencies).phase, 'ready');
  state.jointsDeg[5] = 0.6;
  assert.deepEqual(homeRuntimeStatus(dependencies), {
    phase: 'away', ready: false, reason: 'robot_not_at_home',
    blockers: ['robot_not_at_home'],
  });
});
