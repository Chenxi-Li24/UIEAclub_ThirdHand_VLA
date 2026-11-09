"""Opt-in bounded lease diagnostics; never include payloads or credentials."""
import base64
import hashlib
import json
import os
import sys
import time

STAGES = frozenset(('received', 'task_started', 'verified', 'lock_wait', 'lock_acquired', 'local_reply', 'reply_sent', 'failed'))


class LeaseTiming:
    def __init__(self, *, enabled=None, sink=None, mono=time.monotonic, wall=time.time,
                 limit=12000, window=600):
        self.enabled = os.environ.get('THIRDHAND_SDK_TIMING') == '1' if enabled is None else enabled
        self.sink = sink or (lambda record: print(json.dumps(record, separators=(',', ':')), file=sys.stderr, flush=True))
        self.mono, self.wall = mono, wall
        self.limit, self.window, self.count, self.opened = limit, window, 0, None

    def begin(self, envelope, received=None):
        if not self.enabled:
            return None
        try:
            raw = envelope['payloadBase64url']
            if not isinstance(raw, str) or len(raw) > 16384:
                return None
            value = json.loads(base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4)))
            if value.get('scope') != 'sdk' or value.get('purpose') != 'lease_renew':
                return None
            start, wall = received if received is not None else (self.mono(), self.wall())
            if self.opened is None:
                self.opened = start
            if self.mono() - self.opened >= self.window or self.count >= self.limit:
                return None
            return _Trace(self, start, wall, hashlib.sha256(raw.encode('ascii')).hexdigest(),
                          value.get('issuedAt') if type(value.get('issuedAt')) is int else None)
        except (KeyError, ValueError, TypeError, UnicodeError, AttributeError):
            return None


class _Trace:
    def __init__(self, owner, start, wall, trace, signed):
        self.owner, self.start, self.done = owner, start, False
        self.record = dict(component='sdk_segment_timing', segment='edge', trace=trace,
                           startedAtMs=round(wall * 1000, 3), signedAtMs=signed, marks={})

    def mark(self, stage):
        if stage in STAGES and stage not in self.record['marks']:
            self.record['marks'][stage] = round(max(0, min(60000, (self.owner.mono() - self.start) * 1000)), 3)

    def finish(self, outcome):
        if self.done:
            return
        self.done = True
        owner = self.owner
        if owner.count >= owner.limit or owner.mono() - owner.opened >= owner.window:
            return
        owner.count += 1
        record = {**self.record, 'marks': dict(self.record['marks']),
                  'outcome': outcome if outcome in ('active', 'rejected', 'failed', 'unknown') else 'unknown'}
        try:
            owner.sink(record)
        except Exception:
            pass  # Logging must not change authorization or cancellation.


TIMING = LeaseTiming()
