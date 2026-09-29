from __future__ import annotations

import json
import time

import websockets

from .protocol import validate_request


class GatewayServer:
    def __init__(self, policy, leases, robot, audit=None, host="127.0.0.1", port=31023):
        if host not in {"127.0.0.1", "localhost"} or int(port) != 31023:
            raise ValueError("debug gateway must bind loopback:31023")
        self.policy, self.leases, self.robot, self.audit = policy, leases, robot, audit
        self.host, self.port = host, int(port)
        self.current_joints = ()

    async def handle(self, socket):
        async for payload in socket:
            request_id = None
            try:
                raw = json.loads(payload)
                request_id = raw.get("request_id")
                if raw.get("cmd") == "acquire_lease":
                    lease = self.leases.acquire(str(raw["session_id"]), time.time())
                    response = {"ok": True, "lease_id": lease.lease_id, "expires_at": lease.expires_at}
                    decision = type("LeaseDecision", (), {"ok": True, "reason_code": "LEASE_ACQUIRED"})()
                elif raw.get("cmd") == "heartbeat":
                    lease = self.leases.heartbeat(str(raw["lease_id"]), str(raw["session_id"]), time.time())
                    response = {"ok": True, "lease_id": lease.lease_id, "expires_at": lease.expires_at}
                    decision = type("LeaseDecision", (), {"ok": True, "reason_code": "LEASE_RENEWED"})()
                elif raw.get("cmd") == "release_lease":
                    released = self.leases.release(str(raw["lease_id"]), str(raw["session_id"]))
                    response = {"ok": released, "reason_code": "LEASE_RELEASED" if released else "LEASE_INVALID"}
                    decision = type("LeaseDecision", (), {"ok": released, "reason_code": response["reason_code"]})()
                elif raw.get("cmd") in {"ping", "status", "get_state", "software_stop"}:
                    decision = self.policy.authorize_command(raw)
                    response = await self.robot.send(decision.message) if decision.ok and raw.get("cmd") != "ping" else {"ok": decision.ok, "reason_code": decision.reason_code}
                else:
                    request = validate_request(raw)
                    decision = self.policy.authorize(request, self.leases, self.current_joints, time.time())
                    response = await self.robot.send(decision.message) if decision.ok else {"ok": False, "reason_code": decision.reason_code}
                if self.audit:
                    self.audit.decision(decision, request_id=request_id)
            except Exception as exc:
                response = {"ok": False, "reason_code": "INVALID_REQUEST", "error": str(exc)}
            await socket.send(json.dumps(response))

    async def serve(self):
        return await websockets.serve(self.handle, self.host, self.port)
