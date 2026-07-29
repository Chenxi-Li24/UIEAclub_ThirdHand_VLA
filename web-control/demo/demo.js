'use strict';

const elements = {
  status: document.getElementById('demo-status'),
  stage: document.getElementById('demo-stage'),
  pid: document.getElementById('demo-pid'),
  message: document.getElementById('demo-message'),
  log: document.getElementById('demo-log'),
  lastLog: document.getElementById('last-log'),
  start: document.getElementById('start-demo'),
  continue: document.getElementById('continue-demo'),
  stop: document.getElementById('stop-demo'),
};

let lastText = '';

function render(data) {
  elements.status.textContent = data.state;
  elements.status.dataset.state = data.state;
  elements.stage.textContent = data.stage || 'UNKNOWN';
  elements.pid.textContent = data.owned ? `PID ${data.pid}` : '未占用';
  elements.message.textContent = data.message || '';
  elements.lastLog.textContent = data.last_log || '尚无日志文件';
  const text = (data.log_tail || []).join('\n') || '等待开始…';
  if (text !== lastText) {
    const atBottom =
      elements.log.scrollTop + elements.log.clientHeight >=
      elements.log.scrollHeight - 24;
    elements.log.textContent = text;
    if (atBottom) elements.log.scrollTop = elements.log.scrollHeight;
    lastText = text;
  }
  elements.start.disabled = data.owned;
  elements.continue.disabled =
    !data.owned || data.state !== 'WAITING_CONFIRMATION';
  elements.stop.disabled = !data.owned;
}

async function request(path) {
  const response = await fetch(path, { method: 'POST' });
  const data = await response.json();
  render(data);
  if (!response.ok && data.message) {
    elements.message.textContent = data.message;
  }
}

async function poll() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    render(await response.json());
  } catch (error) {
    elements.status.textContent = 'OFFLINE';
    elements.status.dataset.state = 'FAILED';
    elements.message.textContent = `控制服务不可用：${error.message}`;
    elements.start.disabled = true;
    elements.stop.disabled = true;
  }
}

elements.start.addEventListener('click', () => {
  const confirmed = window.confirm(
    '请把测试物体放在固定 A 点，清空机械臂工作区，' +
    '并确认现场人员和物理急停均已就绪。是否开始？'
  );
  if (confirmed) request('/api/start');
});

elements.stop.addEventListener('click', () => {
  const confirmed = window.confirm(
    '将立即中断当前演示，执行 cleanup 和电机失能，' +
    '机械臂停留在当前位置。是否停止？'
  );
  if (confirmed) request('/api/stop');
});

elements.continue.addEventListener('click', () => {
  request('/api/continue');
});

document.getElementById('scroll-log').addEventListener('click', () => {
  elements.log.scrollTop = elements.log.scrollHeight;
});

poll();
setInterval(poll, 1000);
