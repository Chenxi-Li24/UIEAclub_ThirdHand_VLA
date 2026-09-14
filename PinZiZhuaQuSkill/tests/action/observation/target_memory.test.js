'use strict';

const assert = require('assert/strict');
const { LockedTargetMemory } = require('../../../src/thirdhand_va/action/observation/target_memory');

function target(identityId, depthValid, observedAtMs, pointM) {
  return {
    identityId,
    depthValid,
    identityConfirmed: true,
    armStationary: true,
    observedAtMs,
    preview: {
      previewId: `sha256:${'a'.repeat(64)}`,
      pointM,
      pregraspPointM: pointM && [pointM[0] - 0.1, pointM[1], pointM[2]],
      retreatPointM: pointM,
      stableSamples: depthValid ? 5 : 0,
    },
  };
}

const memory = new LockedTargetMemory();
const initial = target(1, true, 1000, [0.50, 0.05, 0.106]);
memory.observe([initial]);

const partial = target(1, false, 3000, null);
partial.identityConfirmed = false;
const restored = memory.targetFor(1, partial, initial.preview.previewId);
assert.deepEqual(restored.preview.pointM, initial.preview.pointM);
assert.equal(restored.preview.previewId, initial.preview.previewId);
assert.equal(restored.observedAtMs, 3000);

const later = target(1, true, 2000, [0.60, 0.10, 0.30]);
later.preview.previewId = `sha256:${'b'.repeat(64)}`;
memory.observe([later]);
const exact = memory.targetFor(1, partial, initial.preview.previewId);
assert.deepEqual(exact.preview.pointM, initial.preview.pointM,
  'handoff must retrieve the exact evidence-bound preview that created the anchor');

assert.equal(memory.targetFor(1, target(2, false, 3010, null)).identityId, 2,
  'a different RGB identity must never receive cached geometry');

memory.reset();
assert.equal(memory.targetFor(1, partial), partial);

console.log('PASS locked target memory combines fresh RGB identity with frozen depth geometry');
