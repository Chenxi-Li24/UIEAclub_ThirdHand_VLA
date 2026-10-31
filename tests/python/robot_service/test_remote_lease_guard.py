"""Worker-side lease protection with fake clocks and no SDK or CAN access."""
import importlib.util
from pathlib import Path
import threading
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]


def fixture():
    path = ROOT / 'services/robot/src/remote_lease_guard.py'
    assert path.is_file(), 'worker-side lease guard required'
    spec = importlib.util.spec_from_file_location('remote_lease_guard_test', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    clock, events = {'mono': 5., 'wall': 1000.}, []
    guard = m.RemoteLeaseGuard(enabled=True, on_expire=events.append,
        monotonic=lambda: clock['mono'], wall=lambda: clock['wall'], start=False)
    lease = {key: str(uuid4()) for key in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId', 'leaseId')}
    lease.update(hardwareFingerprint='a' * 64, leaseEpoch=1, sequence=0, issuedAt=1000000, expiresAt=1000950)
    return m, guard, clock, events, lease


def test_worker_expiry_latches_before_cleanup_and_runs_callback_outside_guard_lock():
    m, guard, clock, events, lease = fixture(); guard.arm(lease)
    clock['mono'] = 5.95
    assert guard.poll() is True and len(events) == 1
    assert events[0]['binding']['leaseId'] == lease['leaseId'] and events[0]['reason'] == 'lease_expired'
    assert guard.active(lease) is False and guard.poll() is False
    with pytest.raises(m.LeaseGuardError): guard.renew({**lease, 'sequence': 1, 'expiresAt': 1001900, 'issuedAt': 1000950})


def test_no_command_can_use_a_new_lease_to_replay_an_old_queued_binding():
    m, guard, clock, _, lease = fixture(); guard.arm(lease); guard.revoke(lease, 'test_revoke'); guard.poll()
    replacement = {**lease, 'leaseId': str(uuid4()), 'leaseEpoch': 2}; guard.arm(replacement)
    assert guard.active(replacement) is True and guard.active(lease) is False
    with pytest.raises(m.LeaseGuardError): guard.require_active(lease)


def test_command_original_expiry_is_not_extended_by_later_valid_renewals():
    _, guard, clock, _, lease = fixture(); guard.arm(lease)
    clock.update(mono=5.5, wall=1000.5)
    renewed = {**lease, 'sequence': 1, 'issuedAt': 1000500, 'expiresAt': 1001450}; guard.renew(renewed)
    clock.update(mono=5.96, wall=1000.96)
    assert guard.active(renewed) is True and guard.active(lease) is False


def test_wall_rollback_cannot_extend_the_first_monotonic_anchor():
    _, guard, clock, events, lease = fixture(); guard.arm(lease)
    clock.update(mono=5.7, wall=999.8)
    renewed = {**lease, 'sequence': 1, 'issuedAt': 999800, 'expiresAt': 1000750}; guard.renew(renewed)
    clock['mono'] = 5.75; guard.poll()
    assert len(events) == 1 and not guard.active(renewed)


@pytest.mark.parametrize('field,value', [('leaseEpoch', 0), ('sequence', -1), ('expiresAt', 1001001),
    ('hardwareFingerprint', 'not-a-digest'), ('leaseId', 'invalid'), ('expiresAt', 1000000)])
def test_invalid_lease_is_rejected_without_sdk_callback(field, value):
    m, guard, _, events, lease = fixture()
    with pytest.raises(m.LeaseGuardError): guard.arm({**lease, field: value})
    assert events == [] and not guard.active(lease)


def test_renewal_replay_or_changed_executor_never_extends_deadline():
    m, guard, clock, events, lease = fixture(); guard.arm(lease)
    for changed in [{**lease}, {**lease, 'sequence': 1, 'executorEpoch': str(uuid4())}]:
        with pytest.raises(m.LeaseGuardError): guard.renew(changed)
    clock['mono'] = 5.95; guard.poll(); assert len(events) == 1


def test_expired_lease_cannot_be_rearmed_with_same_epoch_even_after_reconnect():
    m, guard, clock, _, lease = fixture(); guard.arm(lease); guard.revoke(lease, 'parent_eof'); guard.poll()
    with pytest.raises(m.LeaseGuardError): guard.arm({**lease, 'connectionId': str(uuid4())})
    guard.arm({**lease, 'leaseEpoch': 2, 'leaseId': str(uuid4())}); assert guard.active(guard.snapshot())


def test_slow_cleanup_never_holds_guard_lock_or_allows_new_generation_to_overtake_it():
    m, guard, _, _, lease = fixture(); entered, release = threading.Event(), threading.Event()
    guard.on_expire = lambda _event: (entered.set(), release.wait(2))
    guard.arm(lease); guard.revoke(lease, 'agent_died')
    thread = threading.Thread(target=guard.poll); thread.start(); assert entered.wait(1)
    try:
        assert guard.active(lease) is False
        with pytest.raises(m.LeaseGuardError): guard.arm({**lease, 'leaseEpoch': 2})
    finally:
        release.set(); thread.join(1)


def test_disabled_guard_keeps_legacy_local_admission_unchanged():
    m, *_ = fixture(); guard = m.RemoteLeaseGuard(enabled=False, on_expire=lambda _: None, start=False)
    assert guard.active(None) is True; guard.require_active(None); guard.close()


@pytest.mark.parametrize('operation', ['renew', 'continuing', 'poll'])
def test_wall_read_stall_cannot_revive_or_permit_a_lease_past_its_old_deadline(operation):
    m, guard, clock, events, lease = fixture(); guard.arm(lease)
    clock.update(mono=5.8, wall=1000.2)
    def stalled_wall():
        clock['mono'] = 6.0
        return clock['wall']
    guard.wall = stalled_wall
    if operation == 'renew':
        with pytest.raises(m.LeaseGuardError):
            guard.renew({**lease, 'sequence': 1, 'issuedAt': 1000200, 'expiresAt': 1001150})
    elif operation == 'continuing':
        assert not guard.active(lease, original_expiry=False)
    else:
        assert guard.poll() is True
    guard.poll(); assert len(events) == 1 and not guard.active(lease, original_expiry=False)


def test_utc_forward_jump_expires_poll_and_continuing_while_rollback_still_cannot_extend():
    _, guard, clock, events, lease = fixture(); guard.arm(lease)
    clock.update(mono=5.1, wall=1001.)
    assert not guard.active(lease, original_expiry=False)
    assert guard.poll() is True and len(events) == 1
