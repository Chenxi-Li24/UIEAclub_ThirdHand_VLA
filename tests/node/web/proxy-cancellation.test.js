'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { RobotProxy } = require('../../../apps/web/src/robot-proxy');

function fixture() {
  const proxy = Object.create(RobotProxy.prototype);
  const sent = [];
  const session = { queue: [], browser: { readyState: 1, send: payload => sent.push(JSON.parse(payload)) } };
  proxy.forwardedMotion = new Map([['demo', session]]);
  proxy.sessions = new Set([session]);
  proxy.languageController = proxy.directionalController = { active: false };
  proxy.controlUncertainAtMs = null;
  proxy.languageUpstream = { getRobotState: () => ({ connected: true, stateFresh: true, stateName: 'IDLE', motionActive: false }) };
  return { proxy, session, sent };
}

test('confirmed stop finalizes admitted proxy requests without declaring completion', () => {
  const { proxy, sent } = fixture();
  proxy._reconcileControl({ type: 'software_stop', complete: true, depowered: true });
  assert.equal(proxy.forwardedMotion.size, 0);
  assert.equal(proxy.hasActiveControl(), false);
  assert.equal(sent[0].request_id, 'demo');
  assert.equal(sent[0].code, 'motion_cancelled');
});

test('transport loss clears stale request records but remains uncertain until fresh idle evidence', () => {
  const { proxy, session, sent } = fixture();
  proxy._abandonControl(session, 'robot_service_disconnected');
  assert.equal(proxy.forwardedMotion.size, 0);
  assert.equal(sent[0].request_id, 'demo');
  assert.equal(sent[0].code, 'execution_uncertain');
  assert.equal(proxy.hasActiveControl(), true);
  const lostAt = proxy.controlUncertainAtMs;
  proxy._reconcileControl({ type: 'robot_state', observedAtMs: lostAt - 1 });
  assert.equal(proxy.hasActiveControl(), true);
  proxy._reconcileControl({ type: 'robot_state', observedAtMs: lostAt + 1 });
  assert.equal(proxy.hasActiveControl(), false);
});
