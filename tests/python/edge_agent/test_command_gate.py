import asyncio
import base64
import json
from pathlib import Path
import sys
import uuid
import sqlite3
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.command_gate import CommandGate
from thirdhand_edge.journal import CommandJournal


def fixture(tmp_path):
    clock = [10000]
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    context = {name: str(uuid.uuid4()) for name in ("deviceId", "bootId", "executorEpoch", "connectionId", "certificateId")}
    lease_id = str(uuid.uuid4())
    class FakeRobot:
        def __init__(self): self.calls = []
        async def submit_envelope(self, value):
            self.calls.append(value)
            return {"state": "stopped" if value["purpose"] == "stop" else "completed", "commandId": value["commandId"]}
    robot = FakeRobot()
    journal = CommandJournal(tmp_path / "commands.sqlite")
    gate = CommandGate(trusted_keys={"test": public}, journal=journal, robot=robot, clock=lambda: clock[0])
    def signed(**overrides):
        payload = {"schema": 1, "keyId": "test", "purpose": "command", **context, "commandId": str(uuid.uuid4()), "leaseId": lease_id, "leaseEpoch": 1, "sequence": 1, "opcode": "connect", "parameters": {}, "issuedAt": clock[0], "expiresAt": clock[0] + 500, **overrides}
        raw = json.dumps(payload).encode()
        b64 = lambda v: base64.urlsafe_b64encode(v).decode().rstrip("=")
        return {"keyId": "test", "payloadBase64url": b64(raw), "signatureBase64url": b64(key.sign(raw))}
    return gate, journal, robot, context, signed, clock


def test_invalid_binding_signature_expiry_and_replay_never_resubmit(tmp_path):
    gate, journal, robot, context, signed, clock = fixture(tmp_path)
    assert robot.calls == []
    valid = signed()
    for bad in (signed(bootId=str(uuid.uuid4())), signed(executorEpoch=str(uuid.uuid4())), signed(certificateId=str(uuid.uuid4())), signed(expiresAt=clock[0]), {**valid, "signatureBase64url": "A" * 86}, signed(opcode="run_shell"), signed(parameters={"authorized": True})):
        assert asyncio.run(gate.handle_envelope(bad, context))["state"] == "rejected"
    assert robot.calls == []
    assert asyncio.run(gate.handle_envelope(valid, context))["state"] == "completed"
    assert asyncio.run(gate.handle_envelope(valid, context))["state"] == "completed"
    assert len(robot.calls) == 1
    assert asyncio.run(gate.handle_envelope(signed(), context))["state"] == "rejected"
    journal.close()


def test_valid_stop_does_not_depend_on_writable_journal(tmp_path):
    gate, journal, robot, context, signed, clock = fixture(tmp_path)
    def failed(*args):
        raise OSError("disk unavailable")
    journal.reserve = failed
    assert asyncio.run(gate.handle_envelope(signed(), context))["state"] == "rejected"
    assert robot.calls == []
    result = asyncio.run(gate.handle_envelope(signed(purpose="stop", opcode="software_stop", leaseId=None, leaseEpoch=0, sequence=0), context))
    assert result["state"] == "stopped"
    assert len(robot.calls) == 1
    journal.close()


def test_stop_skips_locked_journal_without_waiting_and_preserves_signed_operator(tmp_path):
    gate, journal, robot, context, signed, clock = fixture(tmp_path)
    blocker = sqlite3.connect(tmp_path / "commands.sqlite", isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    actor = {"kind": "user", "userId": str(uuid.uuid4()), "trigger": "operator_stop"}
    start = time.monotonic()
    try:
        result = asyncio.run(gate.handle_envelope(signed(purpose="stop", opcode="software_stop", leaseId=None, leaseEpoch=0, sequence=0, actor=actor), context))
        assert result["state"] == "stopped"
        assert time.monotonic() - start < 0.5
        assert robot.calls[0]["actor"] == actor
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
        journal.close()


def test_persist_before_submit_and_uncertain_ack_survives_restart(tmp_path):
    gate, journal, robot, context, signed, clock = fixture(tmp_path)
    command = signed()
    async def lost_ack(value):
        assert journal.lookup(value["commandId"])["state"] == "unknown"
        robot.calls.append(value)
        raise ConnectionError("reply lost")
    robot.submit_envelope = lost_ack
    result = asyncio.run(gate.handle_envelope(command, context))
    assert result["state"] == "unknown"
    journal.close()
    reopened = CommandJournal(tmp_path / "commands.sqlite")
    gate.journal = reopened
    assert asyncio.run(gate.handle_envelope(command, context))["state"] == "unknown"
    assert len(robot.calls) == 1
    reopened.close()


def test_stop_bypasses_busy_command_and_duplicate_id_cannot_change_payload(tmp_path):
    gate, journal, robot, context, signed, clock = fixture(tmp_path)
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked(value):
            robot.calls.append(value)
            if value["purpose"] != "stop":
                entered.set()
                await release.wait()
            return {"commandId": value["commandId"], "state": "stopped" if value["purpose"] == "stop" else "completed"}
        robot.submit_envelope = blocked
        first = signed()
        task = asyncio.create_task(gate.handle_envelope(first, context))
        await asyncio.wait_for(entered.wait(), timeout=2)
        stopped = await gate.handle_envelope(signed(purpose="stop", opcode="software_stop", sequence=0, leaseId=None, leaseEpoch=0), context)
        assert stopped["state"] == "stopped"
        assert (await gate.handle_envelope(signed(commandId=json.loads(base64.urlsafe_b64decode(first["payloadBase64url"] + "=="))["commandId"], opcode="disconnect"), context))["state"] == "rejected"
        release.set()
        await task
    asyncio.run(scenario())
    journal.close()
