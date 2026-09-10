'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

class ClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
}

class FakeElement {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.textContent = '';
    this.disabled = false;
    this.dataset = {};
    this.classList = new ClassList();
    this.listeners = new Map();
  }

  addEventListener(type, listener) { this.listeners.set(type, listener); }
  removeEventListener(type, listener) {
    if (this.listeners.get(type) === listener) this.listeners.delete(type);
  }
  dispatchEvent(event) {
    event.target = this;
    if (typeof event.preventDefault !== 'function') event.preventDefault = () => {};
    this.listeners.get(event.type)?.(event);
  }
}

function fixtureDocument() {
  const ids = [
    'grounding-form', 'grounding-query', 'grounding-submit',
    'grounding-status', 'grounding-result', 'grounding-safety',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, new FakeElement(id)]));
  const targets = new Map();
  return {
    elements,
    targets,
    getElementById(id) { return elements[id] || null; },
    querySelector(selector) {
      const match = selector.match(/^\[data-grounding-identity-id="(\d+)"\]$/);
      return match ? targets.get(Number(match[1])) || null : null;
    },
    querySelectorAll(selector) {
      return selector === '[data-grounding-identity-id]'
        ? [...targets.values()]
        : [];
    },
  };
}

const { createGroundingUI } = require('../../web/js/grounding-ui.js');
const root = fixtureDocument();
const sent = [];
const ui = createGroundingUI({ root, send: value => sent.push(value) });

root.elements['grounding-query'].value = '夹取可乐';
root.elements['grounding-form'].dispatchEvent({ type: 'submit' });
assert.deepEqual(sent, [{ cmd: 'ground_language_target', query: '夹取可乐' }]);

ui.handleState({
  type: 'grounding_state', status: 'analyzing', requestId: 'request-1',
  identityId: null, explanation: null, reason: null,
  provider: 'mock', modelId: 'mock-v1', latencyMs: null,
});
assert.equal(ui.elements.input.disabled, true);
assert.equal(ui.elements.submit.disabled, true);

const item12 = new FakeElement('target-12');
item12.dataset.groundingIdentityId = '12';
const item15 = new FakeElement('target-15');
item15.dataset.groundingIdentityId = '15';
root.targets.set(12, item12);
root.targets.set(15, item15);
ui.handleState({
  type: 'grounding_state', status: 'selected', requestId: 'request-1',
  identityId: 12, explanation: 'ID 12 是可乐瓶。', reason: null,
  provider: 'mock', modelId: 'mock-v1', latencyMs: 3,
});
ui.handleDetections([
  { identity_id: 12, identity_status: 'confirmed' },
  { identity_id: 15, identity_status: 'confirmed' },
]);
assert.equal(ui.targetElement(12), item12);
assert.equal(item12.classList.contains('grounding-selected'), true);
assert.equal(item15.classList.contains('grounding-selected'), false);
assert.match(ui.elements.safety.textContent, /预览，不会执行抓取/);
assert.match(ui.elements.result.textContent, /ID 12/);
assert.equal(ui.elements.input.disabled, false);

for (const unsafeStatus of ['tentative', 'ambiguous', 'occluded']) {
  ui.handleState({
    type: 'grounding_state', status: 'selected', requestId: 'request-1',
    identityId: 12, explanation: 'ID 12 是可乐瓶。', reason: null,
    provider: 'mock', modelId: 'mock-v1', latencyMs: 3,
  });
  ui.handleDetections([{ identity_id: 12, identity_status: unsafeStatus }]);
  assert.equal(ui.selectedIdentityId, null);
  assert.equal(item12.classList.contains('grounding-selected'), false);
  assert.match(ui.elements.status.textContent, /已失效/);
}

ui.handleState({
  type: 'grounding_state', status: 'selected', requestId: 'request-1',
  identityId: 12, explanation: 'ID 12 是可乐瓶。', reason: null,
  provider: 'mock', modelId: 'mock-v1', latencyMs: 3,
});
ui.handleDetections([{ identity_id: 15 }]);
assert.equal(item12.classList.contains('grounding-selected'), false);
assert.equal(ui.selectedIdentityId, null);
assert.match(ui.elements.status.textContent, /已失效/);

for (const [status, field, value] of [
  ['clarify', 'explanation', '请说明是瓶装还是罐装可乐。'],
  ['none', 'explanation', '当前画面未找到可乐。'],
  ['rejected', 'reason', 'identity_not_current'],
  ['error', 'reason', 'provider_timeout'],
]) {
  ui.handleState({
    type: 'grounding_state', status, requestId: 'request-2', identityId: null,
    explanation: field === 'explanation' ? value : null,
    reason: field === 'reason' ? value : null,
    provider: 'mock', modelId: 'mock-v1', latencyMs: 5,
  });
  assert.equal(ui.elements.result.textContent.includes(value), true);
}

root.elements['grounding-query'].value = 'x'.repeat(257);
root.elements['grounding-form'].dispatchEvent({ type: 'submit' });
assert.equal(sent.length, 1);
assert.match(ui.elements.result.textContent, /1–256/);

ui.invalidate('视觉连接已断开');
assert.equal(ui.selectedIdentityId, null);
ui.destroy();
assert.equal(root.elements['grounding-form'].listeners.has('submit'), false);

const source = fs.readFileSync(
  path.resolve(__dirname, '../../web/js/grounding-ui.js'), 'utf8'
);
assert.equal(source.includes('innerHTML'), false);
for (const forbidden of [
  'grasp_object', 'gripper', "cmd: 'servo'", "cmd: 'preset'", 'start_active_view',
]) {
  assert.equal(source.includes(forbidden), false, `UI contains execution path: ${forbidden}`);
}

console.log('PASS VLA browser UI is safe-text, ID-preview-only, and invalidation-aware');
