'use strict';

const { createHash } = require('node:crypto');

function normalize(value, seen) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('canonical JSON rejects non-finite numbers');
    return Object.is(value, -0) ? 0 : value;
  }
  if (typeof value !== 'object') throw new TypeError(`canonical JSON rejects unsupported ${typeof value}`);
  if (seen.has(value)) throw new TypeError('canonical JSON rejects cyclic values');
  seen.add(value);
  try {
    if (Array.isArray(value)) return value.map(item => normalize(item, seen));
    if (Object.getPrototypeOf(value) !== Object.prototype) {
      throw new TypeError('canonical JSON accepts plain objects only');
    }
    const output = {};
    for (const key of Object.keys(value).sort()) output[key] = normalize(value[key], seen);
    return output;
  } finally {
    seen.delete(value);
  }
}

function canonicalize(value) {
  return JSON.stringify(normalize(value, new WeakSet()));
}

function digestPlan(plan) {
  return `sha256:${createHash('sha256').update(canonicalize(plan), 'utf8').digest('hex')}`;
}

module.exports = { canonicalize, digestPlan };
