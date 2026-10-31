"""Bound executor transport. Construction/connection never connects the SDK."""
import asyncio
import json
import time
import uuid
import urllib.error

from .command_gate import CommandGate
from .lease import verify_lease
from .protocol import ProtocolError, parse_json, verify_envelope
from .transport import authenticated_connection


async def connect_bound_device(config, *, robot, trusted_keys, journal, on_ready=None, on_context=None):
    prepare = getattr(robot, "prepare_binding", None)
    if prepare:
        deadline = time.monotonic() + 4.5
        while True:
            try:
                snapshot = await prepare(config.boot_id)
                break
            except urllib.error.HTTPError as exc:
                if exc.code != 409 or time.monotonic() >= deadline:
                    raise ProtocolError("PRIOR_STOP_UNCONFIRMED") from exc
                await asyncio.sleep(0.1)
    else:
        snapshot = await robot.get_context()
    if snapshot.get("deviceId") != config.device_id or snapshot.get("bindingAccepted", snapshot.get("controlAccepted")) is not True:
        raise ProtocolError("HARDWARE_ACCEPTANCE_REQUIRED")
    executor, fingerprint = snapshot["executorEpoch"], snapshot["hardwareFingerprint"]
    clock = lambda: time.time_ns() // 1000000
    async with authenticated_connection(config, executor_epoch=executor) as (ws, context):
        # A reconnect never reuses an old lease. The local service refuses bind
        # while an old lease/unknown stop remains; this is intentionally no retry.
        bound = await robot.bind(context)
        if bound.get("bound") is not True or bound.get("context") != context:
            raise ProtocolError("LOCAL_BINDING_FAILED")
        if on_context:
            await on_context(context)
        ready_deadline = time.monotonic() + 2
        while True:
            current = await robot.get_context()
            if current.get("executorEpoch") != executor or current.get("hardwareFingerprint") != fingerprint:
                raise ProtocolError("EXECUTOR_CHANGED")
            if current.get("controlAccepted") is True:
                break
            if time.monotonic() >= ready_deadline:
                raise ProtocolError("CAPTURE_NOT_READY")
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "bound", "executorEpoch": executor, "hardwareFingerprint": fingerprint, "previousStop": bound.get("previousStop")}))
        raw = await asyncio.wait_for(ws.recv(), timeout=5)
        ack = parse_json(raw.encode("utf-8")) if isinstance(raw, str) else None
        if not isinstance(ack, dict) or ack.get("type") != "bound_ack" or ack.get("context") != context or ack.get("controlAuthorized") is not False:
            raise ProtocolError("CLOUD_BINDING_FAILED")
        gate = CommandGate(trusted_keys=trusted_keys, journal=journal, robot=robot, clock=clock)
        tasks, lease_lock = set(), asyncio.Lock()
        last_pong = time.monotonic()
        pending_ping = None
        if on_ready:
            await on_ready(context)

        async def request(message):
            request_id = message["requestId"]
            try:
                uuid.UUID(request_id)
                payload = verify_envelope(message["envelope"], trusted_keys, context, now_ms=clock())
                if payload.get("purpose") in ("lease_grant", "lease_renew"):
                    async with lease_lock:
                        lease = verify_lease(message["envelope"], trusted_keys, context, now_ms=clock())
                        outcome = await robot.submit_envelope({**lease, "signedEnvelope": message["envelope"]})
                else:
                    outcome = await gate.handle_envelope(message["envelope"], context)
            except Exception:
                outcome = {"state": "rejected", "code": "DEVICE_REQUEST_REJECTED"}
            # Do not forward an arbitrary Robot response or credential diagnostic.
            if not isinstance(outcome, dict) or outcome.get("state") not in ("active", "accepted", "started", "completed", "stopped", "rejected", "failed", "unknown"):
                outcome = {"state": "unknown", "code": "SUBMISSION_RESULT_UNKNOWN"}
            safe = {key: outcome[key] for key in ("state", "commandId", "leaseId", "leaseEpoch", "code") if key in outcome}
            await ws.send(json.dumps({"type": "result", "requestId": request_id, "outcome": safe}, allow_nan=False))

        async def heartbeats():
            nonlocal pending_ping
            while True:
                if time.monotonic() - last_pong > 7:
                    raise ProtocolError("DEVICE_HEARTBEAT_TIMEOUT")
                current = await robot.get_context()
                if current.get("executorEpoch") != executor or current.get("hardwareFingerprint") != fingerprint or current.get("controlAccepted") is not True:
                    raise ProtocolError("EXECUTOR_CHANGED")
                pending_ping = uuid.uuid4().hex
                await ws.send(json.dumps({"type": "ping", "nonce": pending_ping}))
                await asyncio.sleep(config.heartbeat_seconds)

        heartbeat = asyncio.create_task(heartbeats())
        async def receive():
            nonlocal last_pong
            while True:
                raw = await ws.recv()
                if not isinstance(raw, str):
                    raise ProtocolError("TEXT_MESSAGE_REQUIRED")
                message = parse_json(raw.encode("utf-8"))
                if not isinstance(message, dict):
                    raise ProtocolError("INVALID_MESSAGE")
                if message.get("type") == "pong" and message.get("nonce") == pending_ping:
                    last_pong = time.monotonic()
                elif message.get("type") == "request" and set(message) == {"type", "requestId", "envelope"} and len(tasks) < 9:
                    task = asyncio.create_task(request(message))
                    tasks.add(task)
                    def finished(value):
                        tasks.discard(value)
                        if not value.cancelled():
                            value.exception()
                    task.add_done_callback(finished)
                else:
                    raise ProtocolError("INVALID_MESSAGE")
        receiver = asyncio.create_task(receive())
        try:
            done, _ = await asyncio.wait((receiver, heartbeat), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in (receiver, heartbeat, *tasks):
                task.cancel()
            await asyncio.gather(receiver, heartbeat, *tasks, return_exceptions=True)
            # No action retry, reconnect, connect SDK or claimed physical stop.
            # The independent Robot lease deadline remains in force after exit.
