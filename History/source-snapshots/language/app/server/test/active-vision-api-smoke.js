'use strict';

const assert = require('assert/strict');
const { createActiveVisionSnapshot } = require('../active-vision-api');

function snapshot(executionEnabled) {
  return createActiveVisionSnapshot({
    visionStatus: {
      snapshot: () => ({
        robotExecutionEnabled: false,
        activeView: { executionEnabled: false, control: {}, reports: [] },
        targets: [{
          identityId: 7,
          graspGeometryAllowed: true,
          d435SameInstanceVerified: true,
          graspAllowed: false,
          graspReasons: ['physical_grasp_execution_locked'],
        }],
      }),
    },
    activeView: { inFlight: null },
    graspController: {
      snapshot: () => ({ active: false, phase: 'idle' }),
    },
    config: {
      activeView: { requested: false },
      visionSafety: { robotExecutionEnabled: executionEnabled },
    },
    nowMs: () => 1000,
  });
}

const locked = snapshot(false);
assert.equal(locked.robotExecutionEnabled, false);
assert.equal(locked.targets[0].graspAllowed, false);
assert.deepEqual(locked.targets[0].graspReasons, ['physical_grasp_execution_locked']);

const enabled = snapshot(true);
assert.equal(enabled.robotExecutionEnabled, true);
assert.equal(enabled.grasp.executionEnabled, true);
assert.equal(enabled.targets[0].graspAllowed, true);
assert.deepEqual(enabled.targets[0].graspReasons, []);

const missingD435 = snapshot(true);
missingD435.targets[0].d435SameInstanceVerified = false;
// The API recomputes this gate before returning; a geometry preview alone is insufficient.
assert.equal(createActiveVisionSnapshot({
  visionStatus: { snapshot: () => ({
    activeView: { control: {}, reports: [] },
    targets: [{ graspGeometryAllowed: true, d435SameInstanceVerified: false, graspReasons: [] }],
  }) },
  activeView: { inFlight: null },
  graspController: { snapshot: () => ({ phase: 'idle' }) },
  config: { activeView: { requested: false }, visionSafety: { robotExecutionEnabled: true } },
  nowMs: () => 1000,
}).targets[0].graspAllowed, false);

console.log('PASS active-vision API exposes the explicit grasp execution gate');
