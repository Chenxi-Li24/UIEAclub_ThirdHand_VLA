/* Dummy is opt-in. Opening the page never launches a motion process. */
(() => {
  'use strict';
  const el = id => document.getElementById(`dummy-${id}`);
  const section = document.getElementById('sec-dummy');
  if (!section) return;
  const labels = { stopped: '已停止', starting: '正在启动', running: '运行中',
    stopping: '正在停止', failed: '启动/运行失败', external: '外部 Dummy 运行中' };
  const reasons = {
    dummy_external_process: '请先退出终端启动的 Dummy，再由网页管理。',
    dummy_backend_upgrade_required: '3000 后端需要升级到 J1 50°/s 版本。',
    dummy_robot_not_ready: '机械臂未连接或实时反馈不可用。',
    dummy_robot_busy: '机械臂正在运动，请等待停止。',
    dummy_vision_not_ready: '视觉服务未就绪。', dummy_requires_ubuntu: 'Dummy 需在 Ubuntu 运行。',
  };
  let state = null;
  let busy = false;
  let polling = false;
  let frameRequest = null;
  let pendingKeywords = true;
  const message = error => reasons[error] || error || '';
  async function request(endpoint, body, signal) {
    const response = await fetch(`/api/dummy/${endpoint}`, {
      method: body === undefined ? 'GET' : 'POST', cache: 'no-store', signal,
      ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }
  function render() {
    const external = state?.phase === 'external';
    el('phase').textContent = labels[state?.phase] || '无法获取状态';
    el('start').disabled = busy || !state?.available || state.running || !state.backendReady
      || !state.robot?.connected || !state.robot?.stateReady || state.robot?.moving;
    el('stop').disabled = busy || !state?.running || external || state?.phase === 'stopping';
    el('keywords').disabled = busy || Boolean(state?.running);
    if (state?.running && !external) el('keywords').checked = state.keywordsEnabled;
    el('limits').textContent = state?.limits
      ? `J1 ≤ ${state.limits.j1MaxSpeedDegS}°/s · J4 ≤ ${state.limits.j4MaxSpeedDegS}°/s` : '上限未确认';
    el('reason').textContent = message(state?.reason || (!state?.backendReady ? 'dummy_backend_upgrade_required' : ''));
    const observation = state?.observation;
    const joints = observation?.robot_joints_deg;
    el('measured').textContent = joints ? `J1 ${joints[0].toFixed(1)}° / J4 ${joints[3].toFixed(1)}°` : 'J1 — / J4 —';
    el('tracking').textContent = observation
      ? `${observation.mode} · ${observation.status} · ${Math.round(observation.receive_age_ms || 0)} ms`
      : external ? '外部进程仅显示运行状态' : '等待识别';
    reconcilePreview();
  }
  function previewVisible() {
    if (!state?.owned || state.phase !== 'running' || !el('preview-enabled').checked
        || document.hidden || section.closest('.collapsed')) return false;
    const rect = el('preview').getBoundingClientRect();
    return rect.width > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
  }
  function reconcilePreview() {
    el('preview').hidden = !el('preview-enabled').checked || !state?.owned || state.phase !== 'running';
    if (!previewVisible()) {
      frameRequest?.abort();
      el('frame').removeAttribute('src');
      el('preview-status').textContent = '';
    }
  }
  async function poll() {
    if (polling || busy || document.hidden) return;
    polling = true;
    try { state = await request('status', undefined, AbortSignal.timeout(5000)); render(); }
    catch (error) { el('phase').textContent = '状态连接失败'; el('reason').textContent = message(error.message); el('start').disabled = true; }
    finally { polling = false; }
  }
  async function frame() {
    reconcilePreview();
    if (frameRequest || !previewVisible()) return;
    const controller = new AbortController();
    frameRequest = controller;
    const timer = setTimeout(() => controller.abort(), 3000);
    try {
      const packet = await request('frame', undefined, controller.signal);
      if (!controller.signal.aborted && previewVisible() && packet.jpeg_base64) {
        el('frame').src = `data:image/jpeg;base64,${packet.jpeg_base64}`;
        el('preview-status').textContent = `帧 ${packet.state.frame_id} · ${packet.state.status}`;
      }
    } catch (error) {
      if (!controller.signal.aborted) el('preview-status').textContent = message(error.message);
    } finally { clearTimeout(timer); if (frameRequest === controller) frameRequest = null; }
  }
  async function action(endpoint, body) {
    if (busy) return;
    busy = true; render();
    try {
      await request(endpoint, body, AbortSignal.timeout(10000));
      // Ignore older polls that may have started before this command.
      while (polling) await new Promise(resolve => setTimeout(resolve, 20));
      state = await request('status', undefined, AbortSignal.timeout(5000));
      render();
    } catch (error) { el('reason').textContent = message(error.message); }
    finally { busy = false; renderButtons(); }
  }
  function renderButtons() {
    el('start').disabled = busy || !state?.available || state.running || !state.backendReady
      || !state.robot?.connected || !state.robot?.stateReady || state.robot?.moving;
    el('stop').disabled = busy || !state?.running || state.phase === 'external' || state.phase === 'stopping';
    el('keywords').disabled = busy || Boolean(state?.running);
  }
  section.querySelector('.sec-header').addEventListener('click', event => {
    event.stopImmediatePropagation();
    const collapsed = section.classList.toggle('collapsed');
    const toggle = section.querySelector('.sec-toggle');
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.setAttribute('aria-label', `${collapsed ? '展开' : '收起'} Dummy 控制`);
    reconcilePreview();
  }, true);
  el('start').addEventListener('click', () => {
    pendingKeywords = el('keywords').checked;
    el('keyword-warning').hidden = !pendingKeywords;
    el('confirm').showModal();
  });
  el('confirm-cancel').addEventListener('click', () => el('confirm').close());
  el('confirm-start').addEventListener('click', () => {
    el('confirm').close();
    action('start', { authorized: true, keywords: pendingKeywords });
  });
  el('stop').addEventListener('click', () => action('stop', {}));
  el('preview-enabled').addEventListener('change', reconcilePreview);
  document.addEventListener('visibilitychange', () => { reconcilePreview(); poll(); });
  document.addEventListener('scroll', reconcilePreview, true);
  new MutationObserver(reconcilePreview).observe(document.getElementById('control-drawer'),
    { attributes: true, attributeFilter: ['class'], subtree: true });
  window.addEventListener('resize', reconcilePreview);
  const statusTimer = setInterval(poll, 1000);
  const frameTimer = setInterval(frame, 250);
  window.addEventListener('pagehide', event => {
    frameRequest?.abort();
    if (!event.persisted) { clearInterval(statusTimer); clearInterval(frameTimer); }
  });
  poll();
})();
