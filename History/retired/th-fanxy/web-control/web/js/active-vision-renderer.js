'use strict';

(function expose(global) {
  const millimetres = value => Number.isFinite(value) ? `${Math.round(value * 1000)} mm` : '—';
  const vector = value => Array.isArray(value) && value.length === 3
    ? value.map(millimetres).join(' / ') : '—';

  function createActiveVisionRenderer(root = document) {
    const get = id => root.getElementById(id);

    function render(state) {
      const status = state.status;
      const sourceAgeMs = Number.isFinite(status?.sourceAgeMs) ? status.sourceAgeMs : null;
      const depthOnline = state.error === null && status?.online === true &&
        status?.lumosReady === true && status?.stale !== true &&
        status?.roles?.metricDepth === 'xvisio_depth';
      const mode = get('system-mode');
      mode.className = `mode ${depthOnline ? 'online' : state.error ? 'offline' : 'waiting'}`;
      mode.textContent = depthOnline ? 'RGB-D LIVE' : state.error ? 'STREAM OFFLINE' : 'RGB-D WAIT';

      const health = get('depth-health');
      health.className = depthOnline ? '' : 'bad';
      health.textContent = depthOnline ? '深度在线 · 有效边框内可测距'
        : status?.stale === true ? '深度断流 · 禁止沿X前进' : '等待有效深度';
      get('depth-source-age').textContent = sourceAgeMs === null ? '—' : `${Math.round(sourceAgeMs)} ms`;

      const targets = Array.isArray(status?.targets) ? status.targets : [];
      get('target-readout').textContent = targets.length
        ? `目标：${targets.map(target => `#${target.identityId ?? '?'} ${target.identityStatus}`).join(' · ')}`
        : '目标：深度边框内暂无瓶子';
      const measured = targets.filter(target => Array.isArray(target.graspPointM));
      get('depth-readout').textContent = measured.length
        ? `深度/三维：${measured.map(target => `#${target.identityId ?? '?'} ${vector(target.graspPointM)} · ${target.registeredDepthPoints}点`).join(' | ')}`
        : '深度/三维：等待可靠测量';
    }
    return { render };
  }
  global.ThirdHandActiveVisionRenderer = { createActiveVisionRenderer };
})(window);

