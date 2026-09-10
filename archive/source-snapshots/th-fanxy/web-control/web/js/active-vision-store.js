'use strict';

(function expose(global) {
  function createActiveVisionStore({ pollMs = 500 } = {}) {
    const subscribers = new Set();
    let timer = null;
    let state = { status: null, error: null, events: [] };

    function publish(next) {
      state = Object.freeze({ ...state, ...next });
      subscribers.forEach(listener => listener(state));
    }

    function note(event) {
      const label = typeof event === 'string' ? event
        : `${event.type || 'event'}${event.reason ? ` · ${event.reason}` : ''}`;
      const stamped = `${new Date().toLocaleTimeString('zh-CN', { hour12: false })}  ${label}`;
      publish({ events: [stamped, ...state.events].slice(0, 12) });
    }

    async function refresh() {
      try {
        const response = await fetch('/api/active-vision/status', { cache: 'no-store' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        publish({ status: await response.json(), error: null });
      } catch (error) {
        publish({ error: error.message || 'status unavailable' });
      }
    }

    return {
      subscribe(listener) { subscribers.add(listener); listener(state); return () => subscribers.delete(listener); },
      note,
      refresh,
      start() { if (timer) return; refresh(); timer = setInterval(refresh, pollMs); },
      stop() { if (timer) clearInterval(timer); timer = null; },
      snapshot() { return state; },
    };
  }
  global.ThirdHandActiveVisionStore = { createActiveVisionStore };
})(window);
