'use strict';

const assert = require('assert/strict');
const { createLumosStreamSelector } = require('../../web/live-camera-streams');

let visibleSource = null;
let lastStatus = null;
let nextTimerId = 0;
const timers = new Map();
const cancelledTimers = [];
const probes = [];

const selector = createLumosStreamSelector({
  rawUrl: '/camera_lumos',
  overlayUrl: '/camera_lumos_vision',
  applySource: source => { visibleSource = source; },
  report: status => { lastStatus = status; },
  createProbe: () => {
    const probe = { src: '', onload: null, onerror: null };
    probes.push(probe);
    return probe;
  },
  schedule: (callback, milliseconds) => {
    assert.equal(milliseconds, 2500);
    const handle = ++nextTimerId;
    timers.set(handle, callback);
    return handle;
  },
  cancelSchedule: handle => {
    cancelledTimers.push(handle);
    timers.delete(handle);
  },
  timeoutMs: 2500,
});

selector.useRaw();
assert.equal(selector.mode(), 'raw');
assert.equal(visibleSource, '/camera_lumos');
assert.equal(lastStatus, 'raw');

selector.tryOverlay();
assert.equal(selector.mode(), 'checking_overlay');
assert.equal(lastStatus, 'checking_overlay');
assert.equal(probes[0].src, '/camera_lumos_vision');
assert.equal(visibleSource, '/camera_lumos');

const firstTimeout = timers.get(1);
assert.equal(typeof firstTimeout, 'function');
firstTimeout();
assert.equal(selector.mode(), 'raw');
assert.equal(lastStatus, 'overlay_unavailable');
assert.equal(visibleSource, '/camera_lumos');
assert.equal(probes[0].src, '');

probes[0].onload?.();
assert.equal(visibleSource, '/camera_lumos');
assert.equal(selector.mode(), 'raw');

selector.tryOverlay();
assert.equal(probes[1].src, '/camera_lumos_vision');
probes[1].onload();
assert.equal(selector.mode(), 'overlay');
assert.equal(lastStatus, 'overlay');
assert.equal(visibleSource, '/camera_lumos_vision');
assert.equal(cancelledTimers.includes(2), true);

selector.useRaw();
assert.equal(selector.mode(), 'raw');
assert.equal(lastStatus, 'raw');
assert.equal(visibleSource, '/camera_lumos');

selector.tryOverlay();
probes[2].onerror();
assert.equal(selector.mode(), 'raw');
assert.equal(lastStatus, 'overlay_unavailable');
assert.equal(visibleSource, '/camera_lumos');

selector.destroy();
assert.equal(selector.mode(), 'destroyed');
assert.equal(probes[2].src, '');
assert.equal(selector.tryOverlay().accepted, false);

assert.throws(
  () => createLumosStreamSelector({}),
  /rawUrl must be a non-empty string/
);

console.log('PASS Lumos stream selector preserves raw video on overlay failure');
