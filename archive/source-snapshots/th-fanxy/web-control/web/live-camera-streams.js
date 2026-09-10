'use strict';

(function exposeLiveCameraStreams(root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ThirdHandLiveCameraStreams = api;
}(typeof globalThis === 'object' ? globalThis : this, function buildLiveCameraStreamsApi(root) {
  function requireNonEmptyString(value, name) {
    if (typeof value !== 'string' || value.length === 0) {
      throw new TypeError(`${name} must be a non-empty string`);
    }
    return value;
  }

  function requireFunction(value, name) {
    if (typeof value !== 'function') throw new TypeError(`${name} must be a function`);
    return value;
  }

  function createLumosStreamSelector(options) {
    if (!options || typeof options !== 'object' || Array.isArray(options)) {
      throw new TypeError('options must be an object');
    }
    const rawUrl = requireNonEmptyString(options.rawUrl, 'rawUrl');
    const overlayUrl = requireNonEmptyString(options.overlayUrl, 'overlayUrl');
    const applySource = requireFunction(options.applySource, 'applySource');
    const report = requireFunction(options.report, 'report');
    const createProbe = options.createProbe ?? (() => new root.Image());
    const schedule = options.schedule ?? root.setTimeout.bind(root);
    const cancelSchedule = options.cancelSchedule ?? root.clearTimeout.bind(root);
    requireFunction(createProbe, 'createProbe');
    requireFunction(schedule, 'schedule');
    requireFunction(cancelSchedule, 'cancelSchedule');
    const timeoutMs = options.timeoutMs ?? 2500;
    if (!Number.isFinite(timeoutMs) || timeoutMs < 100 || timeoutMs > 30000) {
      throw new TypeError('timeoutMs must be finite and within [100, 30000]');
    }

    let currentMode = 'raw';
    let generation = 0;
    let timerHandle = null;
    let probe = null;
    let destroyed = false;

    function releaseProbe() {
      if (timerHandle !== null) {
        cancelSchedule(timerHandle);
        timerHandle = null;
      }
      if (probe) {
        probe.onload = null;
        probe.onerror = null;
        probe.src = '';
        probe = null;
      }
    }

    function invalidate() {
      generation += 1;
      releaseProbe();
      return generation;
    }

    function reject(reason) {
      return { accepted: false, reason };
    }

    function useRaw() {
      if (destroyed) return reject('selector_destroyed');
      invalidate();
      currentMode = 'raw';
      applySource(rawUrl);
      report('raw');
      return { accepted: true, mode: currentMode };
    }

    function tryOverlay() {
      if (destroyed) return reject('selector_destroyed');
      const attempt = invalidate();
      currentMode = 'checking_overlay';
      report('checking_overlay');
      probe = createProbe();
      if (!probe || typeof probe !== 'object') {
        currentMode = 'raw';
        report('overlay_unavailable');
        return reject('overlay_probe_invalid');
      }

      function fail() {
        if (destroyed || generation !== attempt) return;
        invalidate();
        currentMode = 'raw';
        report('overlay_unavailable');
      }

      function succeed() {
        if (destroyed || generation !== attempt) return;
        invalidate();
        currentMode = 'overlay';
        applySource(overlayUrl);
        report('overlay');
      }

      probe.onload = succeed;
      probe.onerror = fail;
      timerHandle = schedule(fail, timeoutMs);
      probe.src = overlayUrl;
      return { accepted: true, mode: currentMode };
    }

    function destroy() {
      if (destroyed) return;
      invalidate();
      destroyed = true;
      currentMode = 'destroyed';
    }

    function mode() {
      return currentMode;
    }

    return Object.freeze({ useRaw, tryOverlay, destroy, mode });
  }

  return Object.freeze({ createLumosStreamSelector });
}));
