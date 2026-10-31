"""Worker bridge races without importing the native SDK or opening hardware."""
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/robot/src'))


def fixture(monkeypatch, *, real_audit=False):
    spec = importlib.util.spec_from_file_location('worker_guard_bridge_test', ROOT / 'services/robot/src/startouch_bridge.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    from remote_lease_guard import RemoteLeaseGuard
    b = m.RobotBridge.__new__(m.RobotBridge)
    for key, value in {'arm': None, 'connected': False, 'state_ready': False, 'motion_active': False,
        'connection_generation': 0, 'active_motion_cancel': None, 'follow': None, 'release_unconfirmed': False,
        'release_pending_arm': None, 'last_valid_joints': [0] * 6, 'connect_in_progress': False}.items(): setattr(b, key, value)
    b.stop_requested = threading.Event(); b.shutdown_requested = threading.Event()
    b.arm_lock = threading.RLock(); b.disconnect_lock = threading.RLock(); b.motion_queue = queue.Queue()
    calls, events, clock = [], [], {'mono': 5., 'wall': 1000.}
    b._acquire_control_lock = lambda: calls.append('acquire')
    b._release_control_lock = lambda: calls.append('release')
    b._read_can_rx_packets = lambda: 0; b._record_can_rx = lambda _: None
    b._wait_for_stable_state = lambda *_: {'joints': [0] * 6}
    b._emit_snapshot = lambda *_: None; b._emit_joint_log = lambda *_args, **_kwargs: None
    if not real_audit:
        monkeypatch.setattr(m, 'emit', lambda kind, **data: events.append({'type': kind, **data}))
        monkeypatch.setattr(m, 'emit_async', lambda kind, **data: events.append({'type': kind, **data}))
    monkeypatch.setattr(m, 'SIMULATE', True); monkeypatch.setattr(m, 'REQUIRE_CAN_RX', False)
    assert hasattr(b, '_remote_lease_expired'), 'worker expiry must cancel the actual bridge'
    b.remote_lease_guard = RemoteLeaseGuard(enabled=True, start=False, on_expire=b._remote_lease_expired,
        monotonic=lambda: clock['mono'], wall=lambda: clock['wall'])
    lease = {key: str(uuid4()) for key in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId', 'leaseId')}
    lease.update(hardwareFingerprint='a' * 64, leaseEpoch=1, sequence=0, issuedAt=1000000, expiresAt=1000950)
    return m, b, lease, clock, calls, events


def test_remote_connect_without_worker_lease_never_constructs_sdk(monkeypatch):
    m, b, _, _, calls, _ = fixture(monkeypatch)
    monkeypatch.setattr(m, 'SimulatedArm', lambda: pytest.fail('SDK constructor must not run'))
    with pytest.raises(RuntimeError): b.connect()
    assert calls == [] and not b.connected


def test_expiry_during_pending_constructor_refuses_commit_and_releases_only_after_late_cleanup(monkeypatch):
    m, b, lease, clock, calls, events = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    def constructor():
        clock['mono'] = 5.951; b.remote_lease_guard.poll()
        assert 'release' not in calls
        return SimpleNamespace(cleanup=lambda: calls.append('late-cleanup'))
    monkeypatch.setattr(m, 'SimulatedArm', constructor)
    b.connect(lease)
    assert not b.connected and b.stop_requested.is_set()
    assert calls == ['acquire', 'late-cleanup', 'release']
    assert not any(event.get('connected') is True for event in events)


def test_continuously_renewed_same_lease_can_finish_connection_but_new_lease_cannot_rescue_old_constructor(monkeypatch):
    m, b, lease, clock, calls, _ = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    arm = SimpleNamespace(cleanup=lambda: calls.append('cleanup'))
    def settle(*_):
        clock.update(mono=5.5, wall=1000.5)
        b.remote_lease_guard.renew({**lease, 'sequence': 1, 'issuedAt': 1000500, 'expiresAt': 1001450})
        clock.update(mono=6.0, wall=1001.0)
        return {'joints': [0] * 6}
    monkeypatch.setattr(m, 'SimulatedArm', lambda: arm); b._wait_for_stable_state = settle
    b.connect(lease); assert b.connected and b.arm is arm


def test_worker_expiry_cancels_queued_motion_follow_and_gripper_without_claiming_stop(monkeypatch):
    _, b, lease, clock, calls, events = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    b.arm = SimpleNamespace(cleanup=lambda: calls.append('cleanup')); b.connected = b.state_ready = True
    b.active_motion_cancel = threading.Event(); b.follow = SimpleNamespace(active=True)
    b.gripper_target = 0.5; b.motion_queue.put({'request_id': 'queued'})
    clock['mono'] = 5.951; b.remote_lease_guard.poll()
    assert b.active_motion_cancel.is_set() and not b.follow.active and b.gripper_target is None and b.motion_queue.empty()
    assert calls == ['cleanup', 'release']
    assert any(event['type'] == 'remote_lease_expired' and event['stop_state'] == 'unknown' for event in events)


def test_motion_queue_keeps_original_binding_for_a_second_pre_execution_check(monkeypatch):
    _, b, lease, _, _, _ = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    b.connected = b.state_ready = True; b.last_valid_joints = [0.2] * 6
    b.enqueue_motion({'cmd': 'move_joint', 'joints_rad': [0.1, 0.1, -0.1, 0.1, 0.1, 0.1], 'request_id': 'queued', 'remote_lease': lease})
    queued = b.motion_queue.get_nowait()
    assert queued['remote_lease'] == lease
    b.remote_lease_guard.revoke(lease, 'agent_died'); b.remote_lease_guard.poll()
    b.remote_lease_guard.arm({**lease, 'leaseId': str(uuid4()), 'leaseEpoch': 2})
    with pytest.raises(RuntimeError): b._require_remote_lease(queued.get('remote_lease'))


def test_priority_stdin_reader_updates_guard_even_while_main_sdk_command_is_busy(monkeypatch):
    m, b, lease, clock, _, _ = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    inbox, renewed = queue.Queue(), threading.Event()
    class Input:
        def __iter__(self):
            while True:
                value = inbox.get(timeout=2)
                if value is None: return
                yield value
    monkeypatch.setattr(m, 'emit', lambda kind, **data: renewed.set() if kind == 'remote_lease_status' else None)
    assert hasattr(m, 'command_lines'), 'remote stdin requires an independent priority reader'
    inbox.put(json.dumps({'cmd': 'connect', 'remote_lease': lease}))
    lines = m.command_lines(b, Input()); assert json.loads(next(lines))['cmd'] == 'connect'
    clock.update(mono=5.5, wall=1000.5)
    fresh = {**lease, 'sequence': 1, 'issuedAt': 1000500, 'expiresAt': 1001450}
    inbox.put(json.dumps({'cmd': 'remote_lease_renew', 'lease': fresh})); assert renewed.wait(1)
    assert b.remote_lease_guard.active(fresh)
    inbox.put(None)
    with pytest.raises(StopIteration): next(lines)
    assert not b.remote_lease_guard.active(fresh)


def test_normal_stdin_eof_always_runs_bridge_shutdown(monkeypatch):
    m, *_ = fixture(monkeypatch); calls = []
    fake = SimpleNamespace(shutdown_requested=threading.Event(), shutdown=lambda: calls.append('shutdown'))
    monkeypatch.setattr(m, 'RobotBridge', lambda: fake)
    monkeypatch.setattr(m.sys, 'stdin', io.StringIO(''))
    monkeypatch.setattr(m.signal, 'signal', lambda *_: None)
    m.main(); assert calls == ['shutdown']


def test_new_epoch_never_rescues_a_previous_pending_constructor(monkeypatch):
    m, b, lease, _, calls, events = fixture(monkeypatch); b.remote_lease_guard.arm(lease)
    def constructor():
        b.remote_lease_guard.revoke(lease, 'agent_died'); b.remote_lease_guard.poll()
        b.remote_lease_guard.arm({**lease, 'leaseEpoch': 2, 'leaseId': str(uuid4())})
        return SimpleNamespace(cleanup=lambda: calls.append('late-cleanup'))
    monkeypatch.setattr(m, 'SimulatedArm', constructor)
    b.connect(lease)
    assert not b.connected and not any(event.get('connected') is True for event in events)
    pending = [event for event in events if event.get('reason') == 'remote_lease_expired']
    assert pending[0]['sdk_released'] is False


def test_broken_parent_pipe_cannot_prevent_cleanup_with_queued_motion(monkeypatch):
    m, b, lease, clock, calls, _ = fixture(monkeypatch, real_audit=True)
    read_fd, write_fd = os.pipe(); os.close(read_fd)
    output = os.fdopen(write_fd, 'w', buffering=1)
    monkeypatch.setattr(m, '_event_stream', output)
    b.arm = SimpleNamespace(cleanup=lambda: calls.append('cleanup')); b.connected = True
    b.motion_queue.put({'request_id': 'queued'})
    b.remote_lease_guard.arm(lease); clock['mono'] = 5.951
    try:
        b.remote_lease_guard.poll()
        assert calls == ['cleanup', 'release'] and b.motion_queue.empty()
        assert b.remote_lease_guard.stopping is False
    finally:
        output.close()


def test_unread_full_parent_pipe_does_not_hold_cleanup_or_guard_completion(monkeypatch):
    m, b, lease, clock, calls, _ = fixture(monkeypatch, real_audit=True)
    read_fd, write_fd = os.pipe(); output = os.fdopen(write_fd, 'w', buffering=1)
    monkeypatch.setattr(m, '_event_stream', output)
    wrote, cleaned = threading.Event(), threading.Event()
    def write_large():
        wrote.set()
        try: m.emit('log', message='x' * (1024 * 1024))
        except OSError: pass
    writer = threading.Thread(target=write_large, daemon=True); writer.start(); assert wrote.wait(1)
    # Receiving a byte proves the OS pipe is being filled, not only an injected
    # audit callback. The remaining unread large event blocks its writer.
    assert os.read(read_fd, 1)
    b.arm = SimpleNamespace(cleanup=lambda: (calls.append('cleanup'), cleaned.set())); b.connected = True
    b.motion_queue.put({'request_id': 'queued'})
    b.remote_lease_guard.arm(lease); clock['mono'] = 5.951
    runner = threading.Thread(target=b.remote_lease_guard.poll, daemon=True); runner.start()
    try:
        assert cleaned.wait(0.5), 'cleanup must not wait for the unread audit pipe'
        runner.join(0.5); assert not runner.is_alive()
        assert b.motion_queue.empty() and b.remote_lease_guard.stopping is False
    finally:
        def drain():
            try:
                while os.read(read_fd, 65536): pass
            except OSError: pass
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        writer.join(2); runner.join(2); output.close(); reader.join(1); os.close(read_fd)
