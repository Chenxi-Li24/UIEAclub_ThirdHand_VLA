// dashboard.js — Status bar and WebSocket connection
const WS_URL = ws:///ws;
let ws = null;

function connectWebSocket() {
    ws = new WebSocket(WS_URL);
    ws.onopen = () => console.log('[WS] Connected');
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleMessage(data);
    };
    ws.onclose = () => { console.log('[WS] Disconnected'); setTimeout(connectWebSocket, 2000); };
    ws.onerror = (err) => console.error('[WS] Error:', err);
}

function handleMessage(data) {
    switch (data.type) {
        case 'robot_state': updateRobotState(data); break;
        case 'camera_frame': updateCameraFrame(data); break;
        case 'task_event': updateTaskState(data); break;
        case 'log': appendLog(data); break;
    }
}

function updateRobotState(data) {
    const el = document.getElementById('robot-status');
    el.textContent = Robot: ;
    el.className = status-indicator ;
    if (window.updateRobot3D) window.updateRobot3D(data.joints);
}

function appendLog(data) {
    const container = document.getElementById('log-entries');
    const entry = document.createElement('div');
    entry.className = log-entry ;
    entry.textContent = [] [] ;
    container.prepend(entry);
    if (container.children.length > 200) container.lastChild.remove();
}

document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
    document.getElementById('fps-counter').textContent = 'FPS: —';
    document.getElementById('latency').textContent = 'Latency: —ms';
});
