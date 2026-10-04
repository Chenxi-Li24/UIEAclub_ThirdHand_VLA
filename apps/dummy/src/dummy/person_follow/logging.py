from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


FIELDS = (
    "timestamp_utc", "monotonic_ns", "level", "component", "event", "run_id",
    "session_id", "frame_id", "identity_id", "proposal_id", "request_id",
    "state_before", "state_after", "reason_code", "latency_ms",
)


class JsonlEventLogger:
    def __init__(self, path: str | Path, component: str):
        self.path = Path(path)
        self.component = component
        self._lock = Lock()

    def emit(self, event: str, *, level: str = "INFO", **context):
        record = {key: None for key in FIELDS}
        record.update(
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            monotonic_ns=time.monotonic_ns(), level=level,
            component=self.component, event=event,
        )
        record.update({key: value for key, value in context.items() if key in record})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        return record
