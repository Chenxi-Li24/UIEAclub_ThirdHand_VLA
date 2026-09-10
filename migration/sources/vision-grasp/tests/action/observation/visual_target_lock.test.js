'use strict';

const assert = require('assert/strict');
const { VisualTargetLock } = require('../../../src/thirdhand_va/action/observation/visual_target_lock');

function target(identityId, overrides = {}) {
  return {
    identityId,
    actionable: true,
    depthValid: true,
    observedAtMs: 1000,
    preview: {
      previewId: `preview-${identityId}`,
      pointM: [0.50, 0.10, 0.18],
      stableSamples: 5,
    },
    ...overrides,
  };
}

const lock = new VisualTargetLock();
const acquired = lock.acquire([target(7)]);
assert.equal(acquired.accepted, true);
assert.equal(acquired.target.identityId, 7);

// Production bug caught: a partial target with invalid depth must keep the
// visual identity instead of being replaced by a different, depth-valid bottle.
const partial = target(7, {
  actionable: false,
  depthValid: false,
  preview: null,
});
const tracked = lock.track([target(2), partial]);
assert.equal(tracked.accepted, true);
assert.equal(tracked.target.identityId, 7);

const missing = lock.track([target(2)]);
assert.equal(missing.accepted, false);
assert.equal(missing.reason, 'locked_visual_target_missing');
assert.equal(lock.snapshot().identityId, 7);

console.log('PASS visual identity stays locked through partial visibility and depth loss');

