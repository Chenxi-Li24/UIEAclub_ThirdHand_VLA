from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class Lease:
    lease_id: str
    session_id: str
    expires_at: float


class LeaseRegistry:
    def __init__(self, ttl_s=1.0):
        self.ttl_s = float(ttl_s)
        self.active: Lease | None = None

    def acquire(self, session_id: str, now: float):
        if self.active and self.active.expires_at >= now and self.active.session_id != session_id:
            raise RuntimeError("gateway already has an active owner")
        self.active = Lease(str(uuid.uuid4()), session_id, now + self.ttl_s)
        return self.active

    def valid(self, lease_id: str, session_id: str, now: float):
        return bool(self.active and self.active.lease_id == lease_id and self.active.session_id == session_id and now <= self.active.expires_at)

    def heartbeat(self, lease_id: str, session_id: str, now: float):
        if not self.valid(lease_id, session_id, now):
            raise RuntimeError("lease is missing, expired, or owned by another session")
        self.active = Lease(lease_id, session_id, now + self.ttl_s)
        return self.active

    def release(self, lease_id: str, session_id: str):
        if not self.active or self.active.lease_id != lease_id or self.active.session_id != session_id:
            return False
        self.active = None
        return True
