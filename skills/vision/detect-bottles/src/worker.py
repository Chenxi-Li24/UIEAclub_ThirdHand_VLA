"""Read-only bottle detection Skill worker backed by Vision Service."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VISION_BASE_URL = "http://127.0.0.1:3100"
SKILL_ID = "vision.detect-bottles"


def _skill_result(
    *,
    task_id: str,
    trace_id: str,
    status: str,
    code: str,
    message: str,
    output: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "thirdhand.skill-result.v1",
        "taskId": task_id,
        "traceId": trace_id,
        "skillId": SKILL_ID,
        "status": status,
        "reason": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "output": output or {},
    }


def _get_json(path: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
    request = Request(f"{VISION_BASE_URL}{path}", method="GET")
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def status() -> dict[str, Any]:
    try:
        payload = _get_json("/api/vision/status")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return {
            "ready": False,
            "code": "vision_unavailable",
            "message": str(error),
        }
    return {
        "ready": payload.get("status") == "ready",
        "vision": payload,
    }


def invoke(call: dict[str, Any]) -> dict[str, Any]:
    task_id = str(call.get("taskId") or "vision-detect-bottles")
    trace_id = str(call.get("traceId") or "trace-missing")
    try:
        payload = _get_json("/api/vision/status")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return _skill_result(
            task_id=task_id,
            trace_id=trace_id,
            status="failed",
            code="skill_unavailable",
            message="Vision Service is unavailable",
            details={"error": str(error)},
        )

    camera = payload.get("camera") or {}
    inference = payload.get("inference") or {}
    if camera.get("status") != "ready" or inference.get("status") != "ready":
        return _skill_result(
            task_id=task_id,
            trace_id=trace_id,
            status="interrupted",
            code="target_lost",
            message="Vision Service does not have a fresh ready RGB-D detection state",
            output={"vision": payload},
        )

    detection = payload.get("detection")
    return _skill_result(
        task_id=task_id,
        trace_id=trace_id,
        status="completed",
        code="targets_reported",
        message="Vision Service returned the current bottle detection state",
        output={
            "camera": camera,
            "inference": inference,
            "selection": payload.get("selection"),
            "detection": detection,
            "robotControlEnabled": False,
        },
    )


if __name__ == "__main__":
    import sys

    data = json.loads(sys.stdin.read() or "{}")
    operation = data.get("operation", "status")
    result = status() if operation == "status" else invoke(data)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
