"""Process-local software lease cancellation, not independent motor safety.

No SDK or CAN imports. A live Python monitor can request best-effort cleanup
when its parent/agent pauses. Whole-process death, an SDK call holding the GIL,
OS suspension or power loss require independently verified device protection.
"""
import math
import re
import threading
import time

UUID = re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$', re.I)
HASH = re.compile(r'^[a-f0-9]{64}$')
BINDING = ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId',
           'hardwareFingerprint', 'leaseId', 'leaseEpoch')
FIELDS = set(BINDING) | {'sequence', 'issuedAt', 'expiresAt'}


class LeaseGuardError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def require(value, code):
    if not value:
        raise LeaseGuardError(code)


class RemoteLeaseGuard:
    def __init__(self, *, enabled, on_expire, monotonic=time.monotonic, wall=time.time, start=True):
        self.enabled, self.on_expire = enabled is True, on_expire
        self.monotonic, self.wall = monotonic, wall
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.lease = None
        self.deadline = None
        self.anchor = None
        self.last_epoch = 0
        self.last_mono = None
        self.pending = None
        self.stopping = False
        self.thread = None
        if self.enabled and start:
            self.thread = threading.Thread(target=self._monitor, name='remote-lease-watchdog', daemon=True)
            self.thread.start()

    def _fresh_mono(self):
        mono = self.monotonic()
        require(math.isfinite(mono) and mono >= 0
                and (self.last_mono is None or mono >= self.last_mono), 'REMOTE_LEASE_CLOCK_INVALID')
        self.last_mono = mono
        return mono

    def _sample(self):
        # First mono anchors expiry conservatively; the final mono detects a
        # stall during wall-clock sampling against the OLD lease as well.
        mono = self._fresh_mono()
        wall = self.wall() * 1000
        require(math.isfinite(wall), 'REMOTE_LEASE_CLOCK_INVALID')
        return mono, wall, self._fresh_mono()

    def _validate(self, value):
        require(type(value) is dict and set(value) == FIELDS, 'REMOTE_LEASE_INVALID')
        require(all(isinstance(value[key], str) and UUID.fullmatch(value[key])
                    for key in ('deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId', 'leaseId'))
                and isinstance(value['hardwareFingerprint'], str) and HASH.fullmatch(value['hardwareFingerprint']),
                'REMOTE_LEASE_INVALID')
        require(all(type(value[key]) is int for key in ('leaseEpoch', 'sequence', 'issuedAt', 'expiresAt'))
                and value['leaseEpoch'] >= 1 and value['sequence'] >= 0
                and 0 < value['expiresAt'] - value['issuedAt'] <= 1000, 'REMOTE_LEASE_INVALID')
        return dict(value)

    def _latch(self, reason):
        if self.deadline is None:
            return
        self.pending = {'binding': dict(self.lease), 'reason': reason, 'deadline_monotonic': self.deadline,
                        'stop_state': 'unknown', 'controlled_stop_supported': False}
        self.deadline = None
        self.stopping = True

    def _current(self, mono, wall):
        if self.deadline is not None and (mono >= self.deadline or wall >= self.lease['expiresAt']):
            self._latch('lease_expired')
        return self.deadline is not None and not self.stopping and not self.closed.is_set()

    def _deadline(self, value, mono, wall):
        require(value['issuedAt'] <= wall + 500 and 0 < value['expiresAt'] - wall <= 1000,
                'REMOTE_LEASE_EXPIRED')
        return min(mono + 1., mono + (value['expiresAt'] - wall) / 1000,
                   self.anchor[0] + (value['expiresAt'] - self.anchor[1]) / 1000)

    def arm(self, value):
        require(self.enabled and not self.closed.is_set(), 'REMOTE_LEASE_DISABLED')
        value = self._validate(value)
        with self.lock:
            mono, wall, fresh = self._sample()
            require(not self._current(fresh, wall) and not self.stopping, 'REMOTE_LEASE_STOP_PENDING')
            require(value['leaseEpoch'] > self.last_epoch, 'REMOTE_LEASE_REPLAYED')
            self.anchor = (mono, wall)
            deadline = self._deadline(value, mono, wall)
            require(deadline > self._fresh_mono(), 'REMOTE_LEASE_EXPIRED')
            self.lease, self.deadline, self.last_epoch = value, deadline, value['leaseEpoch']
        return self.snapshot()

    def renew(self, value):
        require(self.enabled and not self.closed.is_set(), 'REMOTE_LEASE_DISABLED')
        value = self._validate(value)
        with self.lock:
            mono, wall, fresh = self._sample()
            require(self._current(fresh, wall), 'REMOTE_LEASE_TERMINAL')
            require(all(value[key] == self.lease[key] for key in BINDING)
                    and value['sequence'] > self.lease['sequence'], 'REMOTE_LEASE_REPLAYED')
            deadline = self._deadline(value, mono, wall)
            fresh = self._fresh_mono()
            require(self._current(fresh, wall), 'REMOTE_LEASE_TERMINAL')
            require(deadline > fresh, 'REMOTE_LEASE_EXPIRED')
            self.lease, self.deadline = value, deadline
        return self.snapshot()

    def snapshot(self):
        with self.lock:
            return None if self.lease is None else dict(self.lease)

    def active(self, binding, *, original_expiry=True):
        if not self.enabled:
            return True
        try:
            value = self._validate(binding)
            with self.lock:
                mono, wall, fresh = self._sample()
                if not self._current(fresh, wall) or any(value[key] != self.lease[key] for key in BINDING):
                    return False
                if not original_expiry:
                    return self._current(self._fresh_mono(), wall)
                if value['sequence'] > self.lease['sequence'] or value['expiresAt'] > self.lease['expiresAt']:
                    return False
                deadline = self._deadline(value, mono, wall)
                fresh = self._fresh_mono()
                return self._current(fresh, wall) and deadline > fresh
        except (LeaseGuardError, TypeError, ValueError):
            return False

    def require_active(self, binding, *, original_expiry=True):
        require(self.active(binding, original_expiry=original_expiry), 'REMOTE_LEASE_REQUIRED')

    def revoke(self, binding, reason='authorization_revoked'):
        if not self.enabled:
            return False
        require(isinstance(reason, str) and re.fullmatch(r'[a-z_]{1,64}', reason), 'REMOTE_LEASE_REASON_INVALID')
        value = self._validate(binding)
        with self.lock:
            require(self.lease is not None and all(value[key] == self.lease[key] for key in BINDING), 'REMOTE_LEASE_REPLAYED')
            self._latch(reason)
        return True

    def revoke_current(self, reason):
        value = self.snapshot()
        return False if value is None else self.revoke(value, reason)

    def poll(self):
        if not self.enabled:
            return False
        with self.lock:
            try:
                _mono, wall, fresh = self._sample()
                self._current(fresh, wall)
            except (LeaseGuardError, TypeError, ValueError):
                self._latch('monotonic_clock_invalid')
            event, self.pending = self.pending, None
        if event is None:
            return False
        # SDK cleanup may block; do not hold the guard lock or allow a new
        # generation to overtake the in-progress release of the old executor.
        try:
            self.on_expire(event)
        except Exception:
            return True  # Remain latched when cancellation itself fails.
        with self.lock:
            self.stopping = False
        return True

    def _monitor(self):
        while not self.closed.wait(0.02):
            self.poll()

    def close(self):
        self.closed.set()
