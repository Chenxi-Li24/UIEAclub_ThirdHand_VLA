'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { DepthObservationFilter } = require(
  '../../../src/thirdhand_va/action/observation/depth_filter'
);

let frame = 0;
function target(pointM, overrides = {}) {
  frame += 1;
  const evidenceId = `sha256:${String(frame).padStart(64, '0')}`;
  return {
    depthValid: true,
    armStationary: true,
    motionEpoch: 2,
    observedAtMs: 1000,
    evidenceId,
    preview: {
      pointM,
      stableSamples: 3,
      previewId: `sha256:${String(frame + 100).padStart(64, '0')}`,
      armStateId: `sha256:${String(frame + 200).padStart(64, '0')}`,
    },
    ...overrides,
  };
}

test('depth filter accepts only fresh stationary evidence from its epoch', () => {
  const filter = new DepthObservationFilter({ stableWindow: 3, requiredStableSamples: 3 });
  filter.resetReference(2);

  assert.equal(filter.observe(target([0.5, 0.1, 0.18], {
    motionEpoch: 1,
  }), 1100).reason, 'motion_epoch_mismatch');
  assert.equal(filter.observe(target([0.5, 0.1, 0.18], {
    armStationary: false,
  }), 1100).reason, 'arm_not_stationary');
  let accepted;
  for (let index = 0; index < 3; index += 1) {
    accepted = filter.observe(target([0.5, 0.1, 0.18]), 1100);
  }
  assert.equal(accepted.accepted, true);

  filter.resetReference(3);
  const old = filter.observe(target([0.5, 0.1, 0.18], { motionEpoch: 2 }), 1100);
  assert.equal(old.accepted, false);
  assert.equal(old.reason, 'motion_epoch_mismatch');
  assert.equal(filter.snapshot().stableSamples, 0);
});
