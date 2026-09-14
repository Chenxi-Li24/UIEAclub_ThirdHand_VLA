// task_panel.js — Task selection and control buttons

document.addEventListener('DOMContentLoaded', () => {
    const btnStart = document.getElementById('btn-start');
    const btnPause = document.getElementById('btn-pause');
    const btnStop = document.getElementById('btn-stop');
    const btnEstop = document.getElementById('btn-estop');
    const btnHome = document.getElementById('btn-home');
    const taskDropdown = document.getElementById('task-dropdown');

    btnStart.addEventListener('click', () => {
        const task = taskDropdown.value;
        fetch('/api/task/start?task_name=' + task, { method: 'POST' });
        appendLogUI('info', Starting task: );
    });

    btnPause.addEventListener('click', () => {
        fetch('/api/task/pause', { method: 'POST' });
        appendLogUI('warn', 'Task paused');
    });

    btnStop.addEventListener('click', () => {
        fetch('/api/task/stop', { method: 'POST' });
        appendLogUI('warn', 'Task stopped');
    });

    btnEstop.addEventListener('click', () => {
        if (confirm('EMERGENCY STOP — Are you sure?')) {
            fetch('/api/robot/estop', { method: 'POST' });
            appendLogUI('error', 'EMERGENCY STOP TRIGGERED');
        }
    });

    btnHome.addEventListener('click', () => {
        fetch('/api/robot/home', { method: 'POST' });
        appendLogUI('info', 'Moving to home position');
    });
});

function updateTaskState(data) {
    document.getElementById('task-name').textContent = Task: ;
    document.getElementById('task-state').textContent = State: ;
}

function appendLogUI(level, message) {
    const now = new Date().toISOString().slice(11, 23);
    const container = document.getElementById('log-entries');
    const entry = document.createElement('div');
    entry.className = log-entry ;
    entry.textContent = [] ;
    container.prepend(entry);
}
