"""Source recorder for a separate capture process; never calls SDK connect."""
import asyncio
import time
import uuid
import urllib.error

from .telemetry import normalize_robot_state


def _uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


class CaptureRecorder:
    def __init__(self, outbox, *, versions=None):
        self.outbox, self.versions = outbox, versions or {}
        self.cursor = outbox.source_cursor()

    def _event(self, frame, code, details, *, level="info", cursor=None):
        self.outbox.append_event("device_events", {"eventId": str(uuid.uuid4()), "capturedAt": frame["receivedAt"], "eventCode": code, "level": level, "details": details}, source_cursor=cursor)

    def _gap(self, frame, first, last):
        if last >= first:
            self._event(frame, "capture.source_gap", {"executorEpoch": frame["executorEpoch"], "firstSourceSequence": first, "lastSourceSequence": last}, level="error")

    def consume(self, frame):
        if not isinstance(frame, dict) or frame.get("type") not in ("source_snapshot", "source_heartbeat", "robot_event") or type(frame.get("sequence")) is not int or frame["sequence"] < 0 or not isinstance(frame.get("receivedAt"), str):
            raise ValueError("Invalid source frame")
        if frame["type"] == "source_heartbeat":
            return self.outbox.health()
        if not _uuid(frame.get("executorEpoch")):
            raise ValueError("Invalid source executor")
        cursor = {"executorEpoch": frame["executorEpoch"], "sequence": frame["sequence"]}
        if frame["type"] == "source_snapshot":
            if self.cursor is None:
                self._gap(frame, 1, frame["sequence"])
                self._event(frame, "capture.started", {"executorEpoch": frame["executorEpoch"], "sourceSequence": frame["sequence"]}, cursor=cursor)
            elif self.cursor["executorEpoch"] != frame["executorEpoch"]:
                self._event(frame, "capture.executor_changed", {"previousExecutorEpoch": self.cursor["executorEpoch"], "executorEpoch": frame["executorEpoch"], "sourceSequence": frame["sequence"]}, level="warning", cursor=cursor)
            else:
                if frame["sequence"] < self.cursor["sequence"]:
                    raise ValueError("Source sequence reset inside an executor")
                self._gap(frame, self.cursor["sequence"] + 1, frame["sequence"])
                if frame["sequence"] > self.cursor["sequence"]:
                    self._event(frame, "capture.resumed", {"executorEpoch": frame["executorEpoch"], "sourceSequence": frame["sequence"]}, cursor=cursor)
            self.cursor = cursor
            return self.outbox.health()
        if self.cursor is None or self.cursor["executorEpoch"] != frame["executorEpoch"] or frame["sequence"] <= self.cursor["sequence"]:
            raise ValueError("Source snapshot or fresh sequence required")
        self._gap(frame, self.cursor["sequence"] + 1, frame["sequence"] - 1)
        message = frame.get("message")
        if not isinstance(message, dict):
            raise ValueError("Invalid source message")
        details = {"sourceSequence": frame["sequence"], "executorEpoch": frame["executorEpoch"], "rawState": message}
        if message.get("type") == "robot_state":
            value = normalize_robot_state(message, received_at=frame["receivedAt"], versions=self.versions)
            value["extra"].update({"sourceSequence": frame["sequence"], "executorEpoch": frame["executorEpoch"], "sourceMode": frame.get("sourceMode", "unknown")})
            if frame.get("hardwareFingerprint"):
                value["extra"]["hardwareFingerprint"] = frame["hardwareFingerprint"]
            if _uuid(frame.get("commandId")):
                value["commandId"] = frame["commandId"]
            self.outbox.append_sample(value, source_cursor=cursor)
        elif message.get("type") == "remote_command_outcome" and message.get("opcode") != "software_stop" and _uuid(message.get("commandId")):
            state = message.get("state")
            if state not in ("accepted", "started", "completed", "stopped", "rejected", "failed", "unknown"):
                raise ValueError("Invalid command outcome")
            self.outbox.append_event("command_events", {"eventId": str(uuid.uuid4()), "commandId": message["commandId"], "capturedAt": frame["receivedAt"], "eventCode": "command.outcome", "state": state, "details": details}, source_cursor=cursor)
        else:
            kind = str(message.get("type", "unknown"))
            level = "error" if kind == "error" or message.get("complete") is False else "info"
            self._event(frame, "robot." + kind, details, level=level, cursor=cursor)
        self.cursor = cursor
        return self.outbox.health()


def capture_stream(robot, outbox, *, versions=None):
    """Blocking entry point for a dedicated capture worker, separate from control.

    Exceptions retain buffered data and publish a veto. The caller may reconnect
    the read-only stream; it never reconnects SDK or retries a physical action.
    """
    recorder = CaptureRecorder(outbox, versions=versions)
    last_health = last_seal = 0.0
    def health(writable):
        if not recorder.cursor:
            return
        try:
            asyncio.run(robot.report_capture_health(boot_id=outbox.boot_id, executor_epoch=recorder.cursor["executorEpoch"], writable=writable,
                                                    source_sequence=recorder.cursor["sequence"]))
        except urllib.error.HTTPError as error:
            # prepare-binding may rotate the epoch between the SSE snapshot and
            # this acknowledgement. Never mark that old epoch healthy; continue
            # consuming the already ordered stream to its next snapshot.
            if error.code != 403:
                raise
            current = asyncio.run(robot.get_context())
            if current.get("executorEpoch") == recorder.cursor["executorEpoch"]:
                raise
    try:
        for frame in robot.iter_events():
            status = recorder.consume(frame)
            now = time.monotonic()
            if now - last_health >= 0.5 or not status["writable"]:
                health(status["writable"])
                last_health = now
            if now - last_seal >= 0.5:
                for kind in outbox.STREAMS:
                    while outbox.seal_batch(kind) is not None:
                        pass
                last_seal = now
    finally:
        try:
            for kind in outbox.STREAMS:
                while outbox.seal_batch(kind) is not None:
                    pass
        finally:
            health(False)
