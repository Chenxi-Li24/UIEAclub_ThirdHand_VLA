(function exposePickCommand(globalScope, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (globalScope) globalScope.ThirdHandPickCommand = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildPickCommand() {
  'use strict';

  const LABEL_ALIASES = Object.freeze({
    bottle: ['瓶子', '瓶', '水瓶', '饮料瓶', 'bottle'],
    cup: ['杯子', '杯', 'cup'],
  });

  function identityId(target) {
    const value = Number(target?.identityId);
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function requestedLabel(query) {
    const text = String(query || '').toLowerCase();
    return Object.entries(LABEL_ALIASES)
      .find(([, aliases]) => aliases.some(alias => text.includes(alias)))?.[0] || null;
  }

  function selectPickTarget(query, targets, reports = []) {
    const text = String(query || '').trim();
    if (!text) return { decision: 'none', reason: '指令不能为空', candidates: [] };
    const confirmed = (Array.isArray(targets) ? targets : [])
      .filter(target => identityId(target) !== null && target.identityStatus === 'confirmed');
    const idMatch = text.match(/(?:id\s*#?\s*|编号\s*)(\d+)/i);
    if (idMatch) {
      const requested = Number(idMatch[1]);
      const exact = confirmed.find(target => identityId(target) === requested);
      return exact
        ? { decision: 'select', target: exact, candidates: [exact], reason: `已锁定 ID ${requested}` }
        : { decision: 'none', reason: `当前没有 confirmed 状态的 ID ${requested}`, candidates: [] };
    }

    const label = requestedLabel(text);
    const candidates = label === null ? confirmed : confirmed.filter(target => target.label === label);
    if (candidates.length === 0) {
      return { decision: 'none', reason: '当前画面没有匹配且已确认的目标', candidates: [] };
    }
    if (candidates.length === 1) {
      return { decision: 'select', target: candidates[0], candidates, reason: '唯一目标已锁定' };
    }

    const reportById = new Map((Array.isArray(reports) ? reports : [])
      .map(report => [Number(report?.identityId), report]));
    if (/(中间|中央|正前|d435|深度相机|当前可见)/i.test(text)) {
      const ranked = [...candidates].sort((left, right) => {
        const leftReport = reportById.get(identityId(left));
        const rightReport = reportById.get(identityId(right));
        const leftCentral = Number(leftReport?.centralFraction ?? left.graspCentralFraction ?? -1);
        const rightCentral = Number(rightReport?.centralFraction ?? right.graspCentralFraction ?? -1);
        if (rightCentral !== leftCentral) return rightCentral - leftCentral;
        return Number(right.registeredDepthPoints || 0) - Number(left.registeredDepthPoints || 0);
      });
      if (Number(ranked[0]?.registeredDepthPoints || 0) > 0 ||
          Number(reportById.get(identityId(ranked[0]))?.centralFraction) > 0) {
        return { decision: 'select', target: ranked[0], candidates, reason: '已选择最接近 D435 中心的目标' };
      }
    }
    return {
      decision: 'clarify',
      reason: `发现 ${candidates.length} 个同类目标，请选择持久 ID`,
      candidates,
    };
  }

  function createPickCommand({ store, actions, root = document }) {
    const form = root.getElementById('pick-command-form');
    const input = root.getElementById('pick-command-query');
    const status = root.getElementById('pick-command-status');
    const choices = root.getElementById('pick-command-choices');
    if (![form, input, status, choices].every(Boolean)) throw new Error('pick command UI is incomplete');
    let pendingIdentityId = null;
    let activeViewStarted = false;
    let graspSent = false;
    let lastConfirmedProposalId = null;

    function setStatus(message) { status.textContent = message; }
    function clearChoices() { choices.replaceChildren(); }

    function progress() {
      if (pendingIdentityId === null) return;
      const current = store.snapshot().status;
      const target = current?.targets?.find(item => item.identityId === pendingIdentityId);
      if (!target || target.identityStatus !== 'confirmed') {
        setStatus(`ID ${pendingIdentityId} 已失去 confirmed 状态，流程停止`);
        pendingIdentityId = null;
        return;
      }
      if (current?.grasp?.active && current.grasp.identityId === pendingIdentityId) {
        setStatus(`ID ${pendingIdentityId} 正在执行抓取：${current.grasp.phase}`);
        return;
      }
      if (target.graspAllowed === true && typeof target.graspPreviewId === 'string') {
        if (!graspSent) {
          // `actions.send` may synchronously publish a new status snapshot.
          // Mark the transition first so the subscriber cannot re-enter and
          // submit the same physical command again.
          graspSent = true;
          if (!actions.send({
            cmd: 'grasp_object', identity_id: pendingIdentityId,
            preview_id: target.graspPreviewId,
          })) graspSent = false;
          setStatus(graspSent ? `ID ${pendingIdentityId} 已对心并发送抓取` : '抓取控制通道不可用');
        }
        return;
      }
      if (target.graspGeometryAllowed === true && current?.grasp?.executionEnabled !== true) {
        setStatus(`ID ${pendingIdentityId} 的视觉与抓取点已就绪；真机抓取执行锁尚未开启`);
        return;
      }
      const control = current?.activeView?.control || {};
      if (control.identityId === pendingIdentityId && control.moveReady === true) {
        setStatus(`ID ${pendingIdentityId} 的下一步对心运动已规划，请点击右侧“确认本步观察”`);
        return;
      }
      if (!activeViewStarted) {
        // The store publishes synchronously from `send`; set the guard before
        // crossing that module boundary to keep one query bound to one session.
        activeViewStarted = true;
        if (!actions.send({ cmd: 'start_active_view', identityId: pendingIdentityId })) {
          activeViewStarted = false;
        }
        setStatus(activeViewStarted
          ? `ID ${pendingIdentityId} 已锁定：鱼眼发现 → D435 对心流程已启动`
          : '主动视觉控制通道不可用');
      }
    }

    function choose(target, reason) {
      pendingIdentityId = identityId(target);
      activeViewStarted = false;
      graspSent = false;
      lastConfirmedProposalId = null;
      clearChoices();
      setStatus(`${reason}；目标 ID ${pendingIdentityId}`);
      progress();
    }

    function runQuery(query) {
      const current = store.snapshot().status;
      const result = selectPickTarget(query, current?.targets, current?.activeView?.reports);
      clearChoices();
      if (result.decision === 'select') {
        choose(result.target, result.reason);
        return result;
      }
      pendingIdentityId = null;
      activeViewStarted = false;
      graspSent = false;
      lastConfirmedProposalId = null;
      setStatus(result.reason);
      if (result.decision === 'clarify') {
        result.candidates.forEach(target => {
          const button = root.createElement('button');
          button.type = 'button';
          button.textContent = `${target.label} · ID ${identityId(target)}`;
          button.addEventListener('click', () => choose(target, '已人工消歧'));
          choices.appendChild(button);
        });
      }
      return result;
    }

    function submit(event) {
      event.preventDefault();
      runQuery(input.value);
    }
    form.addEventListener('submit', submit);
    const unsubscribe = store.subscribe(progress);
    const unsubscribeMoveReady = actions.onMoveReady(message => {
      if (pendingIdentityId === null || message.identityId !== pendingIdentityId ||
          typeof message.sessionId !== 'string' || typeof message.proposalId !== 'string' ||
          message.proposalId === lastConfirmedProposalId) return;
      lastConfirmedProposalId = message.proposalId;
      const sent = actions.send({
        cmd: 'confirm_active_view_step',
        sessionId: message.sessionId,
        proposalId: message.proposalId,
      });
      setStatus(sent
        ? `ID ${pendingIdentityId} 的本步 D435 对心已自动确认（单步≤20 mm，速度≤5%）`
        : '本步对心确认发送失败');
    });
    return {
      runQuery,
      destroy() {
        unsubscribeMoveReady(); unsubscribe(); form.removeEventListener('submit', submit);
      },
    };
  }

  return { createPickCommand, selectPickTarget };
});
