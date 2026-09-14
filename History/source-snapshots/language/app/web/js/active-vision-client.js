'use strict';

(function start() {
  const { createActiveVisionStore } = window.ThirdHandActiveVisionStore;
  const { createActiveVisionRenderer } = window.ThirdHandActiveVisionRenderer;
  const { createActiveVisionActions } = window.ThirdHandActiveVisionActions;
  const { createPickCommand } = window.ThirdHandPickCommand;
  const store = createActiveVisionStore();
  const renderer = createActiveVisionRenderer();
  const actions = createActiveVisionActions({ store });
  const pickCommand = createPickCommand({ store, actions });

  function bindFeed(id) {
    const image = document.getElementById(id);
    const state = document.getElementById(`${id}-state`);
    let usingFallback = false;
    image.addEventListener('load', () => { state.textContent = usingFallback ? '原始画面 · 算法叠加暂不可用' : '实时画面'; });
    image.addEventListener('error', () => {
      state.textContent = '视频流重连中';
      const fallback = image.dataset.fallback;
      if (!usingFallback && fallback) { usingFallback = true; image.src = `${fallback}?t=${Date.now()}`; return; }
      const source = usingFallback ? fallback : image.getAttribute('src').split('?')[0];
      setTimeout(() => { image.src = `${source}?t=${Date.now()}`; }, 1500);
    });
  }

  bindFeed('lumos-feed'); bindFeed('d435-feed');
  store.subscribe(renderer.render);
  store.start(); actions.connect();
  setInterval(() => { document.getElementById('clock').textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false }); }, 1000);
  window.addEventListener('beforeunload', () => {
    pickCommand.destroy(); store.stop(); actions.destroy();
  });
})();
