"""Real local worker process in explicit SIMULATE mode, never SDK/CAN."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[3]


def test_simulated_worker_expires_and_cancels_itself_without_parent_renewals():
    env = dict(os.environ, STARTOUCH_SIMULATE='1', STARTOUCH_DRY_RUN='0', STARTOUCH_REMOTE_LEASE_GUARD='1',
               STARTOUCH_REQUIRE_CAN_RX='0', STARTOUCH_INIT_SETTLE_SEC='0', STARTOUCH_INIT_SAMPLE_COUNT='2',
               STARTOUCH_SPEED_SCALE='0.05', STARTOUCH_POLL_INTERVAL_MS='50')
    env.pop('STARTOUCH_EVENT_FD', None)
    process = subprocess.Popen([sys.executable, '-u', str(ROOT / 'services/robot/src/startouch_bridge.py')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    events, received = [], queue.Queue()
    def read():
        for line in process.stdout:
            value = json.loads(line); events.append(value); received.put(value)
    threading.Thread(target=read, daemon=True).start()
    def wait(predicate):
        until = time.monotonic() + 4
        while time.monotonic() < until:
            value = received.get(timeout=max(0.01, until - time.monotonic()))
            if predicate(value): return value
        raise AssertionError('simulator event timeout')
    def send(value):
        process.stdin.write(json.dumps(value) + '\n'); process.stdin.flush()
    try:
        ready = wait(lambda e: e['type'] == 'bridge_ready')
        assert ready['simulated'] is True and ready['remote_lease_guard'] is True
        assert ready['remote_lease_protocol'] == 'thirdhand-worker-lease-v1'
        now = time.time_ns() // 1_000_000
        lease = {key: str(uuid4()) for key in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId', 'leaseId')}
        lease.update(hardwareFingerprint='a' * 64, leaseEpoch=1, sequence=0, issuedAt=now, expiresAt=now + 950)
        send({'cmd': 'remote_lease_arm', 'lease': lease})
        wait(lambda e: e['type'] == 'remote_lease_status' and e['active'] is True)
        send({'cmd': 'connect', 'remote_lease': lease})
        wait(lambda e: e['type'] == 'connection' and e.get('connected') is True)
        send({'cmd': 'move_joint', 'remote_lease': lease, 'request_id': 'simulated-movement',
              'joints_rad': [0.349, 0.1, -0.1, 0, 0, 0]})
        wait(lambda e: e['type'] == 'motion_state' and e.get('state') == 'MOVING')
        # stdin remains open and the parent sends no stop or renewal command.
        expiry = wait(lambda e: e['type'] == 'remote_lease_expired')
        stopped = next((e for e in events if e['type'] == 'connection' and e.get('reason') == 'remote_lease_expired'), None)
        if stopped is None:
            stopped = wait(lambda e: e['type'] == 'connection' and e.get('reason') == 'remote_lease_expired')
        assert expiry['binding']['leaseId'] == lease['leaseId'] and expiry['stop_state'] == 'unknown'
        assert stopped['connected'] is False and stopped['sdk_released'] is True
        assert stopped['stop_state'] == 'unknown' and stopped.get('depowered') is not True
        assert sum(e['type'] == 'remote_lease_expired' for e in events) == 1
        assert not any(e.get('type') == 'command_complete' and e.get('request_id') == 'simulated-movement' for e in events)
    finally:
        process.stdin.close()
        try: process.wait(timeout=4)
        except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=2)
        process.stdout.close(); process.stderr.close()
