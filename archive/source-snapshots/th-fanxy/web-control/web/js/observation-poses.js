'use strict';

(function start() {
  const labels = { table_center: '桌面中心', table_left: '桌面左侧', table_right: '桌面右侧', table_front: '桌面近侧', table_back: '桌面远侧' };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' })[character]);
  let status = null;

  async function refresh() {
    const response = await fetch('/api/observation-poses/status', { cache: 'no-store' });
    status = await response.json();
    document.getElementById('progress').textContent = `${status.captured} / 5`;
    document.getElementById('pose-list').innerHTML = status.requiredPoseIds.map(poseId => {
      const done = status.capturedPoseIds.includes(poseId);
      return `<article class="target ${done ? 'ready' : ''}"><header><h3>${escape(labels[poseId])}</h3><span class="id">${done ? '已采集' : '待采集'}</span></header><p class="state-body">${escape(poseId)}</p><button class="js-capture primary" data-pose-id="${escape(poseId)}" ${!status.robot?.simulated && status.robot?.connected && status.robot?.stateFresh && status.robot?.stationary ? '' : 'disabled'}>${done ? '重新采集当前位' : '采集当前静止姿态'}</button></article>`;
    }).join('');
    const robot = status.robot || {};
    document.getElementById('robot-state').innerHTML = `<div class="state-grid"><span>运行模式</span><b>${robot.simulated ? 'SIMULATOR · 禁止采集' : 'REAL ROBOT'}</b><span>连接</span><b>${robot.connected ? 'CONNECTED' : 'OFFLINE'}</b><span>状态新鲜</span><b>${robot.stateFresh ? 'YES' : 'NO'}</b><span>完全静止</span><b>${robot.stationary ? 'YES' : 'NO'}</b><span>关节</span><b>${escape(Array.isArray(robot.jointsDeg) ? robot.jointsDeg.map(v => v.toFixed(1)).join(', ') : '—')}</b></div>`;
  }

  document.addEventListener('click', async event => {
    const button = event.target.closest('.js-capture'); if (!button || button.disabled) return;
    button.disabled = true;
    const response = await fetch('/api/observation-poses/capture', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ pose_id: button.dataset.poseId }) });
    const result = await response.json();
    document.getElementById('capture-result').textContent = result.accepted ? `${labels[result.poseId]} 已采集；还剩 ${result.remaining} 个` : `拒绝：${result.reason}`;
    await refresh();
  });
  refresh(); setInterval(refresh, 1000);
})();
