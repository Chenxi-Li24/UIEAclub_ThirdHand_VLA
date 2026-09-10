'use strict';

(function start() {
  const { createActiveVisionStore } = window.ThirdHandActiveVisionStore;
  const { createActiveVisionRenderer } = window.ThirdHandActiveVisionRenderer;
  const store = createActiveVisionStore();
  const renderer = createActiveVisionRenderer();

  function bindFeed(id) {
    const image = document.getElementById(id);
    const state = document.getElementById(`${id}-state`);
    const badge = state.closest('.live-badge');
    let usingFallback = false;
    image.addEventListener('load', () => {
      badge.classList.remove('offline');
      state.textContent = usingFallback ? '原始画面 · 叠加重连中' : '算法融合实时画面';
    });
    image.addEventListener('error', () => {
      badge.classList.add('offline');
      state.textContent = '视频流重连中';
      const fallback = image.dataset.fallback;
      if (!usingFallback && fallback) {
        usingFallback = true;
        image.src = `${fallback}?t=${Date.now()}`;
        return;
      }
      const source = usingFallback ? fallback : image.getAttribute('src').split('?')[0];
      setTimeout(() => { image.src = `${source}?t=${Date.now()}`; }, 1200);
    });
  }

  bindFeed('fusion-feed');
  store.subscribe(renderer.render);
  store.start();
  setInterval(() => {
    document.getElementById('clock').textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  }, 1000);
  window.addEventListener('beforeunload', () => store.stop());
})();

