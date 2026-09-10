'use strict';

(function expose(global) {
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
  const vector = value => Array.isArray(value)
    ? `[${value.map(item => Number(item).toFixed(3)).join(', ')}] m` : '—';
  const percent = value => Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : '—';
  const short = value => typeof value === 'string' ? `${value.slice(0, 18)}…` : '—';

  function createActiveVisionRenderer(root = document) {
    const get = id => root.getElementById(id);

    function renderPipeline(status) {
      const stages = [
        ['Lumos 采集', status?.lumosReady],
        ['RTMDet 轮廓', status?.modelReady],
        ['DINOv3 身份', status?.targets?.some(item => item.identityStatus === 'confirmed')],
        ['D435 在线', status?.d435Ready],
        ['D435 同物确认', status?.targets?.some(item => item.d435SameInstanceVerified)],
        ['抓取几何', status?.targets?.some(item => item.graspPointM)],
        ['执行门禁', status?.robotExecutionEnabled],
      ];
      get('pipeline-stages').innerHTML = stages.map(([label, ready]) =>
        `<li class="${ready ? 'ok' : 'blocked'}">${escape(label)}<small>${ready ? ' READY' : ' WAIT'}</small></li>`).join('');
    }

    function targetCard(target) {
      const blockers = Array.isArray(target.graspReasons) ? target.graspReasons : [];
      const canObserve = target.identityStatus === 'confirmed';
      const canGrasp = target.graspAllowed === true && typeof target.graspPreviewId === 'string';
      return `<article class="target ${canGrasp ? 'ready' : ''}">
        <header><h3>${escape(target.label)} <span class="id">ID#${escape(target.identityId ?? '?')}</span></h3><span>${percent(target.score)}</span></header>
        <div class="chips"><span class="chip">${escape(target.identityStatus)}</span><span class="chip">${escape(target.targetState)}</span><span class="chip">depth ${escape(target.registeredDepthPoints)}</span></div>
        <dl class="metrics">
          <dt>三维中心</dt><dd>${escape(vector(target.positionM))}</dd>
          <dt>D435 同一目标</dt><dd>${target.d435SameInstanceVerified ? '已确认' : '待确认'}</dd>
          <dt>D435 掩膜支持</dt><dd>${escape(target.d435SupportPoints)} · ${escape(percent(target.d435SupportFraction))}</dd>
          <dt>抓取点</dt><dd>${escape(vector(target.graspPointM))}</dd>
          <dt>D435 像素</dt><dd>${escape(Array.isArray(target.graspPointD435Px) ? target.graspPointD435Px.map(Math.round).join(', ') : '—')}</dd>
          <dt>稳定样本</dt><dd>${escape(target.graspStableSamples)} / 5</dd>
          <dt>中心覆盖</dt><dd>${escape(percent(target.graspCentralFraction))}</dd>
          <dt>物体宽 / 高</dt><dd>${Number.isFinite(target.graspWidthM) ? `${(target.graspWidthM * 1000).toFixed(0)} / ${(target.objectHeightM * 1000).toFixed(0)} mm` : '—'}</dd>
          <dt>抓取许可</dt><dd>${canGrasp ? '允许' : '禁止'}</dd>
          <dt>门禁原因</dt><dd>${escape(blockers.join(' · ') || 'none')}</dd>
        </dl>
        <div class="target-actions">
          <button class="js-observe" data-identity-id="${escape(target.identityId)}" ${canObserve ? '' : 'disabled'}>主动观察</button>
          <button class="js-grasp primary" data-identity-id="${escape(target.identityId)}" data-preview-id="${escape(target.graspPreviewId || '')}" ${canGrasp ? '' : 'disabled'}>执行抓取</button>
        </div>
      </article>`;
    }

    function renderTargets(status) {
      const targets = Array.isArray(status?.targets) ? status.targets : [];
      get('target-count').textContent = String(targets.length);
      get('target-list').innerHTML = targets.length
        ? targets.map(targetCard).join('')
        : '<p class="empty">当前没有稳定目标，请把物体放在桌面上并保持相机画面清晰。</p>';
    }

    function renderActiveView(status) {
      const control = status?.activeView?.control || {};
      const report = status?.activeView?.reports?.find(item => item.identityId === control.identityId)
        || status?.activeView?.reports?.[0];
      get('active-view-state').innerHTML = `<div class="state-grid">
        <span>阶段</span><b>${escape(control.phase || 'idle')}</b>
        <span>目标 ID</span><b>${escape(control.identityId ?? '—')}</b>
        <span>观察位</span><b>${escape(control.targetPoseId || report?.targetPoseId || '—')}</b>
        <span>中心覆盖</span><b>${escape(percent(report?.centralFraction))}</b>
        <span>稳定样本</span><b>${escape(report?.stableSamples ?? 0)} / 5</b>
        <span>证据</span><b>${escape((control.evidenceIdsShort || []).join(' · ') || '—')}</b>
      </div>`;
      const confirm = control.moveReady === true;
      const active = Boolean(control.sessionId);
      get('active-view-controls').innerHTML = `
        <button class="js-confirm-view primary" data-session-id="${escape(control.sessionId || '')}" data-proposal-id="${escape(control.proposalId || '')}" ${confirm ? '' : 'disabled'}>确认本步观察</button>
        <button class="js-cancel-view danger" data-session-id="${escape(control.sessionId || '')}" ${active ? '' : 'disabled'}>取消会话</button>`;
    }

    function renderGrasp(status) {
      const grasp = status?.grasp || {};
      get('grasp-state').innerHTML = `<div class="state-grid">
        <span>执行权限</span><b>${grasp.executionEnabled ? 'ENABLED' : 'LOCKED'}</b>
        <span>状态</span><b>${escape(grasp.phase || 'idle')}</b>
        <span>目标 ID</span><b>${escape(grasp.identityId ?? '—')}</b>
        <span>预览证据</span><b>${escape(short(grasp.previewId))}</b>
        <span>请求</span><b>${escape(grasp.requestId || '—')}</b>
      </div>`;
    }

    function renderBlockers(status, error) {
      const blockers = [...new Set([
        ...(Array.isArray(status?.blockers) ? status.blockers : []),
        ...(error ? [`status_error:${error}`] : []),
      ])];
      if (!status?.robotExecutionEnabled) blockers.push('physical_execution_locked');
      get('global-blockers').innerHTML = blockers.length
        ? blockers.map(item => `<li>${escape(item)}</li>`).join('')
        : '<li class="clear">全部门禁通过</li>';
    }

    function renderEvents(events) {
      get('event-log').innerHTML = events.length
        ? events.map(item => `<li>${escape(item)}</li>`).join('')
        : '<li>等待事件</li>';
    }

    function render(state) {
      const status = state.status;
      const mode = get('system-mode');
      mode.className = `mode ${state.error ? 'offline' : status?.robotExecutionEnabled ? 'online' : status?.online ? 'locked' : 'waiting'}`;
      mode.textContent = state.error ? 'STATUS OFFLINE' : status?.robotExecutionEnabled
        ? 'EXECUTION READY' : status?.online ? 'VISION LIVE · MOTION LOCKED' : 'CAMERA STARTING';
      renderPipeline(status); renderTargets(status); renderActiveView(status);
      renderGrasp(status); renderBlockers(status, state.error); renderEvents(state.events);
    }
    return { render };
  }
  global.ThirdHandActiveVisionRenderer = { createActiveVisionRenderer };
})(window);
