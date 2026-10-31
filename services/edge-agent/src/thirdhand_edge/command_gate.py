"""Verify, validate, persist, submit once; the Robot Service rechecks authority."""
import hashlib
import math
import uuid

from .journal import JournalConflict
from .protocol import ProtocolError, decode_b64, verify_envelope

LIMITS = ((-162, 162), (-12, 201), (-183, 0), (-98, 98), (-98, 98), (-164, 164))


def _uuid(value):
    if not isinstance(value, str):
        raise ProtocolError("INVALID_ID")
    try:
        uuid.UUID(value)
    except ValueError as exc:
        raise ProtocolError("INVALID_ID") from exc


def validate_command(payload):
    fields = {"schema", "keyId", "purpose", "deviceId", "bootId", "executorEpoch", "connectionId", "certificateId", "commandId", "leaseId", "leaseEpoch", "sequence", "opcode", "parameters", "issuedAt", "expiresAt"}
    if set(payload) - fields - {"actor"} or not fields <= set(payload) or payload["purpose"] not in ("command", "stop"):
        raise ProtocolError("INVALID_COMMAND")
    for field in ("deviceId", "bootId", "executorEpoch", "connectionId", "certificateId", "commandId"):
        _uuid(payload[field])
    if type(payload["sequence"]) is not int or not 0 <= payload["sequence"] <= 9007199254740991:
        raise ProtocolError("INVALID_SEQUENCE")
    if type(payload["leaseEpoch"]) is not int or not 0 <= payload["leaseEpoch"] <= 9007199254740991:
        raise ProtocolError("INVALID_LEASE")
    opcode, params = payload["opcode"], payload["parameters"]
    if not isinstance(params, dict):
        raise ProtocolError("INVALID_PARAMETERS")
    if payload["purpose"] == "stop":
        if opcode != "software_stop" or params or payload["leaseId"] is not None or payload["leaseEpoch"] != 0:
            raise ProtocolError("INVALID_STOP")
        actor = payload.get("actor")
        if actor is not None:
            import re
            if not isinstance(actor, dict) or set(actor) != {"kind", "userId", "trigger"} or actor["kind"] not in ("user", "system") or not isinstance(actor["trigger"], str) or not re.fullmatch(r"[a-z_]{1,64}", actor["trigger"]):
                raise ProtocolError("INVALID_STOP_ACTOR")
            if actor["kind"] == "user":
                _uuid(actor["userId"])
            elif actor["userId"] is not None:
                raise ProtocolError("INVALID_STOP_ACTOR")
        return
    if "actor" in payload:
        raise ProtocolError("INVALID_COMMAND")
    _uuid(payload["leaseId"])
    if payload["leaseEpoch"] < 1:
        raise ProtocolError("INVALID_LEASE")
    if opcode in ("connect", "disconnect") and not params:
        return
    if opcode == "move_joint" and set(params) <= {"joints", "timeSec"} and "joints" in params:
        joints = params["joints"]
        if not isinstance(joints, list) or len(joints) != 6 or any(type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high for v, (low, high) in zip(joints, LIMITS)):
            raise ProtocolError("INVALID_JOINTS")
        if "timeSec" in params and (type(params["timeSec"]) not in (int, float) or not math.isfinite(params["timeSec"]) or not 0.5 <= params["timeSec"] <= 30):
            raise ProtocolError("INVALID_DURATION")
        return
    if opcode == "gripper" and set(params) == {"position"} and type(params["position"]) in (int, float) and math.isfinite(params["position"]) and 0 <= params["position"] <= 1:
        return
    if opcode == "preset" and set(params) == {"name"} and params["name"] in ("home", "zero", "observe"):
        return
    raise ProtocolError("UNSUPPORTED_OPERATION")


class CommandGate:
    def __init__(self, *, trusted_keys, journal, robot, clock):
        self.keys, self.journal, self.robot, self.clock = trusted_keys, journal, robot, clock
        self.busy = False

    async def handle_envelope(self, envelope, context):
        try:
            payload = verify_envelope(envelope, self.keys, context, now_ms=self.clock())
            validate_command(payload)
            digest = hashlib.sha256(decode_b64(envelope["payloadBase64url"])).hexdigest()
        except ProtocolError as exc:
            return {"state": "rejected", "code": str(exc)}
        writable = True
        recorded = {"commandId": payload["commandId"], "state": "unknown", "code": "SUBMISSION_RESULT_UNKNOWN"}
        try:
            fresh, recorded = self.journal.reserve(payload, digest)
            if not fresh:
                return recorded
            if self.busy and payload["purpose"] != "stop":
                result = {"commandId": payload["commandId"], "state": "rejected", "code": "ROBOT_BUSY"}
                self.journal.finish(payload["commandId"], result)
                return result
        except JournalConflict as exc:
            return {"state": "rejected", "code": str(exc)}
        except Exception:
            if payload["purpose"] != "stop":
                return {"state": "rejected", "code": "JOURNAL_UNAVAILABLE"}
            # An already verified priority stop must not wait for writable storage.
            writable = False
        ordinary = payload["purpose"] != "stop"
        if ordinary:
            self.busy = True
        try:
            # The local server checks its own executor, lease, freshness and watchdog.
            result = await self.robot.submit_envelope({**payload, "signedEnvelope": envelope})
            if not isinstance(result, dict) or result.get("commandId") != payload["commandId"] or result.get("state") not in ("accepted", "started", "completed", "stopped", "rejected", "failed", "unknown"):
                result = recorded
            # A closed result schema keeps local exceptions and credentials out of history.
            result = {"commandId": payload["commandId"], "state": result["state"], **({"code": result["code"]} if isinstance(result.get("code"), str) and len(result["code"]) <= 80 else {})}
            if writable:
                try:
                    self.journal.finish(payload["commandId"], result, priority=not ordinary)
                except Exception:
                    if ordinary:
                        raise
                    # The actual Robot stopped ACK remains authoritative when
                    # an auxiliary receipt write fails; source capture retains
                    # its own independent event path.
                    if result["state"] == "stopped":
                        result["code"] = "STOP_CONFIRMED_JOURNAL_UNAVAILABLE"
            return result
        except Exception:
            return recorded
        finally:
            if ordinary:
                self.busy = False
