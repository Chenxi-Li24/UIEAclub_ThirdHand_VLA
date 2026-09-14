'use strict';

(function expose(global) {
  function createActiveVisionActions({ store, root = document }) {
    let socket = null;
    let reconnect = null;
    const moveReadyListeners = new Set();

    function send(payload) {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        store.note('控制通道未连接，命令未发送');
        return false;
      }
      socket.send(JSON.stringify(payload));
      store.note(`已发送 ${payload.cmd}`);
      return true;
    }

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(`${protocol}//${location.host}/ws`);
      socket.addEventListener('open', () => store.note('控制通道已连接'));
      socket.addEventListener('close', () => {
        store.note('控制通道断开');
        clearTimeout(reconnect); reconnect = setTimeout(connect, 1200);
      });
      socket.addEventListener('message', event => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'active_view_move_ready') {
          moveReadyListeners.forEach(listener => listener(message));
        }
        if (['active_view_state', 'active_view_move_ready', 'active_view_command_result',
          'grasp_status', 'grasp_command_result', 'vision_error', 'camera_error'].includes(message.type)) {
          store.note(message);
          store.refresh();
        }
      });
    }

    function handleClick(event) {
      const button = event.target.closest('button');
      if (!button || button.disabled) return;
      if (button.classList.contains('js-observe')) {
        send({ cmd: 'start_active_view', identityId: Number(button.dataset.identityId) });
      } else if (button.classList.contains('js-confirm-view')) {
        send({ cmd: 'confirm_active_view_step', sessionId: button.dataset.sessionId,
          proposalId: button.dataset.proposalId });
      } else if (button.classList.contains('js-cancel-view')) {
        send({ cmd: 'cancel_active_view', sessionId: button.dataset.sessionId });
      } else if (button.classList.contains('js-grasp')) {
        send({ cmd: 'grasp_object', identity_id: Number(button.dataset.identityId),
          preview_id: button.dataset.previewId });
      }
    }

    root.addEventListener('click', handleClick);
    return {
      connect,
      send,
      onMoveReady(listener) {
        if (typeof listener !== 'function') throw new TypeError('listener must be a function');
        moveReadyListeners.add(listener);
        return () => moveReadyListeners.delete(listener);
      },
      destroy() {
        clearTimeout(reconnect); moveReadyListeners.clear(); socket?.close();
        root.removeEventListener('click', handleClick);
      },
    };
  }
  global.ThirdHandActiveVisionActions = { createActiveVisionActions };
})(window);
