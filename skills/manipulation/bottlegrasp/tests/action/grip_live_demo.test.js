'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { main } = require('../../scripts/action/grip_live_demo');

const calibrationId = `sha256:${'a'.repeat(64)}`;
const gripValidationId = `sha256:${'b'.repeat(64)}`;
const coordinates = {
  camera_xyz_m: [0.1, 0.2, 0.3],
  surface_xyz_m: [0.3, 0.1, 0.2],
  grip_target_xyz_m: [0.31, 0.1, 0.2],
};

function preview(overrides = {}) {
  return {
    previewId: 'preview-1', targetId: 2,
    createdAtMs: 1000, expiresAtMs: 2000,
    coordinates, evidence: { calibrationId, gripValidationId },
    blockers: [], executable: true,
    plan: { requestId: 'request-2' }, ...overrides,
  };
}

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test('blocked preview never issues a motion request', async () => {
  const calls = [];
  const output = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, method: options.method || 'GET' });
    if (url.endsWith('/health')) return response({ camera_ready: true, robot_control_enabled: false, home: { ready: false } });
    if (url.endsWith('/api/va/test/status')) return response({ active: false, phase: 'idle' });
    return response(preview({ blockers: ['grip_transform_unverified'], executable: false, plan: null }));
  };
  const result = await main(['--target-id', '2', '--execute'], {
    fetchImpl, write: line => output.push(line), writeError: line => output.push(line),
    ask: async () => { throw new Error('must not prompt'); },
  });
  assert.equal(result, 2);
  assert.ok(output.join('\n').includes('grip_transform_unverified'));
  assert.ok(calls.every(call => call.method === 'GET'));
});

test('refreshed target drift blocks execution after operator consent', async () => {
  const calls = [];
  let previewCount = 0;
  const fetchImpl = async (url, options = {}) => {
    calls.push(options.method || 'GET');
    if (url.endsWith('/health')) return response({ camera_ready: true, robot_control_enabled: true, home: { ready: true } });
    if (url.endsWith('/api/va/test/status')) return response({ active: false, phase: 'idle' });
    previewCount += 1;
    return response(preview(previewCount === 2 ? {
      coordinates: { ...coordinates, grip_target_xyz_m: [0.33, 0.1, 0.2] },
    } : {}));
  };
  const result = await main(['--target-id', '2', '--execute'], {
    fetchImpl, now: () => 1100, ask: async () => 'START 2',
    write: () => {}, writeError: () => {},
  });
  assert.equal(result, 2);
  assert.equal(previewCount, 2);
  assert.ok(calls.every(method => method === 'GET'));
});

test('each supervised command requires a matching phase confirmation', async () => {
  const posts = [];
  const prompts = [];
  let started = false;
  let advanced = false;
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith('/health')) return response({ camera_ready: true, robot_control_enabled: true, home: { ready: true } });
    if (url.endsWith('/api/va/test/preview?target_id=2')) return response(preview());
    if (url.endsWith('/api/va/test/status')) {
      return response(!started ? { active: false, phase: 'idle' } : advanced
        ? { active: false, phase: 'complete' }
        : { active: true, phase: 'awaiting_confirmation', commandPhase: 'open', awaiting_confirmation: true, requestId: 'request-2' });
    }
    posts.push({ url, body: JSON.parse(options.body) });
    if (url.endsWith('/start')) { started = true; return response({ accepted: true }, 202); }
    if (url.endsWith('/next')) { advanced = true; return response({ accepted: true }, 202); }
    throw new Error(`unexpected request: ${url}`);
  };
  const result = await main(['--target-id', '2', '--execute'], {
    fetchImpl, now: () => 1100, wait: async () => {},
    ask: async message => { prompts.push(message); return prompts.length === 1 ? 'START 2' : 'NEXT open'; },
    id: () => 'confirmation-1', write: () => {}, writeError: () => {},
  });
  assert.equal(result, 0);
  assert.deepEqual(posts.map(post => post.url.split('/').pop()), ['start', 'next']);
  assert.deepEqual(posts[0].body, { previewId: 'preview-1', requestId: 'request-2' });
  assert.deepEqual(posts[1].body, {
    confirmationId: 'confirmation-1', expectedPhase: 'open', requestId: 'request-2',
  });
});

test('failed phase command requests a supervised stop', async () => {
  const posts = [];
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith('/health')) return response({ camera_ready: true, robot_control_enabled: true, home: { ready: true } });
    if (url.endsWith('/api/va/test/preview?target_id=2')) return response(preview());
    if (url.endsWith('/api/va/test/status')) return response(posts.length === 0
      ? { active: false, phase: 'idle' }
      : { active: true, phase: 'awaiting_confirmation', commandPhase: 'open', awaiting_confirmation: true, requestId: 'request-2' });
    posts.push(url.split('/').pop());
    if (url.endsWith('/start')) return response({ accepted: true }, 202);
    if (url.endsWith('/next')) return response({ accepted: false, reason: 'target_lost' }, 423);
    return response({ accepted: true }, 202);
  };
  const result = await main(['--target-id', '2', '--execute'], {
    fetchImpl, now: () => 1100, wait: async () => {}, id: () => 'confirmation-1',
    ask: async message => message.includes('START') ? 'START 2' : 'NEXT open',
    write: () => {}, writeError: () => {},
  });
  assert.equal(result, 3);
  assert.deepEqual(posts, ['start', 'next', 'stop']);
});
