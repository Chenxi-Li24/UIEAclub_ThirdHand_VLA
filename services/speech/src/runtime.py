"""Runtime readiness helpers for the speech service."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping


def readiness_payload(model_status: Mapping[str, Any]) -> dict[str, Any]:
    """Describe listener readiness separately from ASR model readiness."""
    model_state = str(model_status.get("state", "STOPPED"))
    return {
        "ready": True,
        "serviceId": "speech",
        "pid": os.getpid(),
        "modelReady": model_state == "READY",
        "modelState": model_state,
    }


def write_ready_file(
    path: str | Path,
    model_status: Mapping[str, Any],
) -> dict[str, Any]:
    """Atomically publish readiness after the WebSocket listener is bound."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = readiness_payload(model_status)
    temporary = target.with_name(f"{target.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return payload


def remove_ready_file(path: str | Path) -> None:
    """Remove stale readiness state without failing shutdown."""
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
