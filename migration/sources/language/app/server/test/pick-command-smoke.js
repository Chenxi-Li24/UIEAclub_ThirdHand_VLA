'use strict';

const assert = require('assert/strict');
const { createPickCommand, selectPickTarget } = require('../../web/js/pick-command');

const targets = [
  { identityId: 1, identityStatus: 'confirmed', label: 'bottle', registeredDepthPoints: 19000 },
  { identityId: 2, identityStatus: 'confirmed', label: 'bottle', registeredDepthPoints: 0 },
  { identityId: 3, identityStatus: 'tentative', label: 'bottle', registeredDepthPoints: 20000 },
];
const reports = [
  { identityId: 1, centralFraction: 0.28 },
  { identityId: 2, centralFraction: 0 },
];

assert.equal(selectPickTarget('夹取瓶子', targets, reports).decision, 'clarify');
assert.equal(selectPickTarget('夹取中间的瓶子', targets, reports).target.identityId, 1);
assert.equal(selectPickTarget('夹取 ID 2', targets, reports).target.identityId, 2);
assert.equal(selectPickTarget('夹取 ID 3', targets, reports).decision, 'none');
assert.equal(selectPickTarget('夹取杯子', targets, reports).decision, 'none');

function commandHarness(status) {
  let subscriber = () => {};
  const commands = [];
  const elements = {
    'pick-command-form': {
      addEventListener() {},
      removeEventListener() {},
    },
    'pick-command-query': { value: '' },
    'pick-command-status': { textContent: '' },
    'pick-command-choices': {
      replaceChildren() {},
      appendChild() {},
    },
  };
  const store = {
    snapshot: () => ({ status }),
    subscribe(callback) {
      subscriber = callback;
      return () => {};
    },
  };
  const actions = {
    send(command) {
      commands.push(command);
      assert.ok(commands.length <= 1, 'synchronous status publication must not resend the command');
      subscriber();
      return true;
    },
    onMoveReady() { return () => {}; },
  };
  const root = {
    getElementById: id => elements[id],
    createElement: () => ({ addEventListener() {} }),
  };
  return { command: createPickCommand({ store, actions, root }), commands };
}

{
  const status = {
    targets: [{
      identityId: 1, identityStatus: 'confirmed', label: 'bottle',
      registeredDepthPoints: 19_000, graspAllowed: false,
      graspGeometryAllowed: false,
    }],
    activeView: { reports: [], control: {} },
    grasp: { executionEnabled: false },
  };
  const harness = commandHarness(status);
  harness.command.runQuery('夹取瓶子');
  assert.deepEqual(harness.commands, [{ cmd: 'start_active_view', identityId: 1 }]);
}

{
  const status = {
    targets: [{
      identityId: 1, identityStatus: 'confirmed', label: 'bottle',
      registeredDepthPoints: 19_000, graspAllowed: true,
      graspGeometryAllowed: true, graspPreviewId: 'preview-1',
    }],
    activeView: { reports: [], control: {} },
    grasp: { executionEnabled: true },
  };
  const harness = commandHarness(status);
  harness.command.runQuery('夹取瓶子');
  assert.deepEqual(harness.commands, [{
    cmd: 'grasp_object', identity_id: 1, preview_id: 'preview-1',
  }]);
}

console.log('PASS pick command selects only current confirmed persistent IDs');
