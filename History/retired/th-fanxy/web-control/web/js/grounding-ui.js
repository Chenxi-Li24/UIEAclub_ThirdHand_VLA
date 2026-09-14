(function exposeGroundingUI(globalScope, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (globalScope) globalScope.ThirdHandGroundingUI = api;
})(typeof window !== 'undefined' ? window : globalThis, function buildGroundingUI() {
  'use strict';

  const SAFETY_TEXT = 'GPT 仅选择已有视觉 ID：预览，不会执行抓取。';
  const TARGET_SELECTOR = '[data-grounding-identity-id]';

  function boundedText(value, maximum = 512) {
    if (typeof value !== 'string') return '';
    return Array.from(value.trim()).slice(0, maximum).join('');
  }

  function identityOf(target) {
    const value = target && (target.identity_id ?? target.identityId ?? target.id);
    const number = Number(value);
    return Number.isSafeInteger(number) && number >= 0 ? number : null;
  }

  function identityStatusOf(target) {
    const value = target && (target.identity_status ?? target.identityStatus);
    return typeof value === 'string' ? value : null;
  }

  function createGroundingUI({ root, send }) {
    if (!root || typeof root.getElementById !== 'function') {
      throw new TypeError('root must provide getElementById');
    }
    if (typeof send !== 'function') throw new TypeError('send must be a function');
    const elements = {
      form: root.getElementById('grounding-form'),
      input: root.getElementById('grounding-query'),
      submit: root.getElementById('grounding-submit'),
      status: root.getElementById('grounding-status'),
      result: root.getElementById('grounding-result'),
      safety: root.getElementById('grounding-safety'),
    };
    if (Object.values(elements).some(value => !value)) {
      throw new TypeError('grounding UI elements are incomplete');
    }

    let selectedIdentityId = null;
    let activeRequestId = null;
    let destroyed = false;

    function setBusy(value) {
      elements.input.disabled = value;
      elements.submit.disabled = value;
    }

    function clearHighlight() {
      for (const element of root.querySelectorAll(TARGET_SELECTOR)) {
        element.classList.remove('grounding-selected');
      }
    }

    function targetElement(identityId) {
      if (!Number.isSafeInteger(identityId) || identityId < 0) return null;
      return root.querySelector(`[data-grounding-identity-id="${identityId}"]`);
    }

    function applyHighlight() {
      clearHighlight();
      if (selectedIdentityId === null) return;
      targetElement(selectedIdentityId)?.classList.add('grounding-selected');
    }

    function renderLocalError(message) {
      setBusy(false);
      elements.status.textContent = '输入未接受';
      elements.result.textContent = boundedText(message);
    }

    function submit(event) {
      event.preventDefault();
      if (destroyed) return;
      const query = elements.input.value.trim();
      const length = Array.from(query).length;
      if (length < 1 || length > 256) {
        renderLocalError('请输入 1–256 个字符的目标描述');
        return;
      }
      selectedIdentityId = null;
      activeRequestId = null;
      clearHighlight();
      elements.status.textContent = '已提交语义选择';
      elements.result.textContent = '';
      setBusy(true);
      const accepted = send({ cmd: 'ground_language_target', query });
      if (accepted === false) renderLocalError('服务器连接不可用');
    }

    function handleState(event) {
      if (destroyed || !event || event.type !== 'grounding_state') return false;
      const requestId = boundedText(event.requestId, 64) || null;
      if (event.status === 'analyzing') {
        activeRequestId = requestId;
        selectedIdentityId = null;
        clearHighlight();
        setBusy(true);
        elements.status.textContent = 'GPT 正在选择视觉 ID';
        elements.result.textContent = '';
        return true;
      }
      if (activeRequestId && requestId && requestId !== activeRequestId) return false;
      setBusy(false);
      const explanation = boundedText(event.explanation);
      const reason = boundedText(event.reason, 128);
      if (event.status === 'selected' && Number.isSafeInteger(event.identityId) &&
          event.identityId >= 0) {
        selectedIdentityId = event.identityId;
        elements.status.textContent = '已选择视觉目标（仅预览）';
        elements.result.textContent = `视觉 ID ${event.identityId}：${explanation}`;
        applyHighlight();
        return true;
      }
      selectedIdentityId = null;
      clearHighlight();
      const labels = {
        clarify: '需要补充目标描述',
        none: '未找到匹配目标',
        rejected: '选择已被安全校验拒绝',
        error: '语义选择不可用',
      };
      if (!Object.prototype.hasOwnProperty.call(labels, event.status)) return false;
      elements.status.textContent = labels[event.status];
      elements.result.textContent = explanation || reason || '无可用详情';
      return true;
    }

    function invalidate(reason = '当前预览已失效') {
      if (destroyed) return;
      selectedIdentityId = null;
      activeRequestId = null;
      clearHighlight();
      setBusy(false);
      elements.status.textContent = '预览已失效';
      elements.result.textContent = boundedText(reason, 128);
    }

    function handleDetections(targets) {
      if (destroyed || !Array.isArray(targets)) return false;
      if (selectedIdentityId !== null) {
        const current = targets.filter(target => identityOf(target) === selectedIdentityId);
        if (current.length !== 1 || identityStatusOf(current[0]) !== 'confirmed') {
          invalidate('目标 ID 已消失或不再处于 confirmed 状态，请重新选择');
          return false;
        }
      }
      applyHighlight();
      return true;
    }

    function destroy() {
      if (destroyed) return;
      clearHighlight();
      setBusy(false);
      elements.form.removeEventListener('submit', submit);
      destroyed = true;
    }

    elements.safety.textContent = SAFETY_TEXT;
    elements.status.textContent = '等待目标描述';
    elements.result.textContent = '';
    elements.form.addEventListener('submit', submit);

    const api = {
      elements,
      handleState,
      handleDetections,
      invalidate,
      destroy,
      targetElement,
    };
    Object.defineProperty(api, 'selectedIdentityId', {
      enumerable: true,
      get: () => selectedIdentityId,
    });
    return api;
  }

  return { SAFETY_TEXT, createGroundingUI };
});
