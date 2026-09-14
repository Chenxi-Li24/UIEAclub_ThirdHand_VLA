'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { canonicalize, digestPlan } = require('../../../platform/authorization/src/canonical-json');

test('canonical plan digest ignores object key order but preserves array order', () => {
  assert.equal(digestPlan({ b: 2, a: 1 }), digestPlan({ a: 1, b: 2 }));
  assert.notEqual(digestPlan({ steps: ['a', 'b'] }), digestPlan({ steps: ['b', 'a'] }));
});

test('canonical JSON rejects non-finite and undefined values', () => {
  assert.throws(() => canonicalize({ value: Number.NaN }), /non-finite/);
  assert.throws(() => canonicalize({ value: undefined }), /unsupported/);
});
