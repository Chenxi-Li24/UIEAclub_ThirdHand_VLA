"""Stop receipt semantics without importing SDK, opening CAN or starting workers."""
import importlib.util
from pathlib import Path
import queue
import sys
import threading
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'services/robot/src'))
spec = importlib.util.spec_from_file_location('stop_receipt_bridge', ROOT / 'services/robot/src/startouch_bridge.py')
bridge_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge_module)


def quiet_bridge(monkeypatch, *, cleanup_error=None):
    calls, events, released = [], [], []
    def cleanup():
        calls.append('cleanup')
        if cleanup_error:
            raise RuntimeError(cleanup_error)
    arm = SimpleNamespace(cleanup=cleanup)
    bridge = bridge_module.RobotBridge.__new__(bridge_module.RobotBridge)
    bridge.stop_requested = threading.Event()
    bridge.arm_lock = threading.RLock()
    bridge.connection_generation = 0
    bridge.active_motion_cancel = None
    bridge.motion_queue = queue.Queue()
    bridge.arm = arm
    bridge.connected = True
    bridge.state_ready = True
    bridge.follow = None
    bridge._release_control_lock = lambda: released.append(True)
    monkeypatch.setattr(bridge_module, 'emit', lambda kind, **data: events.append({'type': kind, **data}))
    monkeypatch.setattr(bridge_module, 'emit_async', lambda kind, **data: events.append({'type': kind, **data}))
    monkeypatch.setattr(bridge_module, 'SIMULATE', False)
    monkeypatch.setattr(bridge_module, 'DRY_RUN', False)
    return bridge, calls, events, released


def test_cleanup_success_releases_sdk_but_does_not_claim_physical_stop(monkeypatch):
    bridge, calls, events, released = quiet_bridge(monkeypatch)
    bridge.disconnect('software_stop', request_id='stop-1')
    result = events[-1]
    assert calls == ['cleanup'] and released == [True]
    assert result['request_id'] == 'stop-1'
    assert result['sdk_released'] is True
    assert result['cleanup_state'] == 'completed'
    assert result['stop_state'] == 'unknown'
    assert result['stop_code'] == 'STOP_FEEDBACK_UNAVAILABLE'
    assert result['source_mode'] == 'hardware'
    assert result.get('depowered') is not True


def test_cleanup_failure_retains_exclusive_lock_and_does_not_expose_exception(monkeypatch):
    bridge, calls, events, released = quiet_bridge(monkeypatch, cleanup_error='credential=do-not-log')
    bridge.disconnect('software_stop', request_id='stop-2')
    result = events[-1]
    assert calls == ['cleanup'] and released == []
    assert result['sdk_released'] is False
    assert result['cleanup_state'] == 'failed'
    assert result['stop_state'] == 'unknown'
    assert result['stop_code'] == 'SDK_RELEASE_FAILED'
    assert 'credential=do-not-log' not in repr(events)
    assert bridge.release_unconfirmed is True


def test_explicit_retry_can_release_sdk_without_claiming_hardware_stop(monkeypatch):
    bridge, calls, events, released = quiet_bridge(monkeypatch, cleanup_error='temporary')
    bridge.disconnect('software_stop', request_id='stop-3')
    bridge.release_pending_arm.cleanup = lambda: calls.append('retry-cleanup')
    bridge.disconnect('software_stop', request_id='stop-4')
    assert calls == ['cleanup', 'retry-cleanup']
    assert released == [True]
    assert events[-1]['sdk_released'] is True
    assert events[-1]['stop_state'] == 'unknown'
    assert bridge.release_unconfirmed is False


def test_failed_release_refuses_new_sdk_connection(monkeypatch):
    bridge, _, events, _ = quiet_bridge(monkeypatch, cleanup_error='failed')
    bridge.disconnect('software_stop', request_id='stop-5')
    bridge.connect()
    assert events[-1]['connected'] is False
    assert events[-1]['code'] == 'SDK_RELEASE_UNCONFIRMED'


def test_failed_initialization_cleanup_also_retains_lock_and_prevents_reconnect(monkeypatch, tmp_path):
    bridge, calls, events, released = quiet_bridge(monkeypatch, cleanup_error='private-cleanup-error')
    arm = bridge.arm
    bridge.connected = False
    bridge.motion_active = False
    bridge._acquire_control_lock = lambda: None
    bridge._read_can_rx_packets = lambda: 0
    def unavailable(*_):
        raise RuntimeError('private-initialization-error')
    bridge._wait_for_stable_state = unavailable
    monkeypatch.setattr(bridge_module, 'REQUIRE_CAN_RX', False)
    monkeypatch.setattr(bridge_module, 'SDK_PATH', str(tmp_path))
    monkeypatch.setattr(bridge_module, 'MODULE_PATH', str(tmp_path))
    monkeypatch.setattr(bridge_module, 'validate_sdk_speed_reference', lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, 'startouchclass', SimpleNamespace(SingleArm=lambda **_kwargs: arm))
    bridge.connect()
    assert calls == ['cleanup'] and released == []
    assert bridge.release_unconfirmed is True
    assert bridge.release_pending_arm is arm
    assert events[-1]['code'] == 'SDK_RELEASE_FAILED'
    assert 'private-initialization-error' not in repr(events)
    assert 'private-cleanup-error' not in repr(events)
    bridge.connect()
    assert events[-1]['code'] == 'SDK_RELEASE_UNCONFIRMED'
