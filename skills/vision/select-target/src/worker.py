"""Read-only Vision Service target selection Skill worker."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VISION_BASE_URL = "http://127.0.0.1:3100"
SKILL_ID = "vision.select-target"


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


def _json_request(path: str, *, method: str, body: dict[str, Any] | None = None, timeout_s: float = 2.0) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        f"{VISION_BASE_URL}{path}",
        data=data,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def status() -> dict[str, Any]:
    try:
        payload = _json_request("/api/vision/status", method="GET")
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
    task_id = str(call.get("taskId") or "vision-select-target")
    trace_id = str(call.get("traceId") or "trace-missing")
    body = call.get("input") or {}
    action = body.get("action")

    if action == "select":
        stable_id = body.get("stableId")
        if not isinstance(stable_id, int) or stable_id < 1 or stable_id > 5:
            return _skill_result(
                task_id=task_id,
                trace_id=trace_id,
                status="failed",
                code="schema_invalid",
                message="stableId must be an integer from 1 through 5",
            )
        endpoint = "/api/vision/select"
        request_body = {"stableId": stable_id}
    elif action == "release":
        endpoint = "/api/vision/release"
        request_body = {}
    else:
        return _skill_result(
            task_id=task_id,
            trace_id=trace_id,
            status="failed",
            code="schema_invalid",
            message="action must be select or release",
        )

    try:
        response = _json_request(endpoint, method="POST", body=request_body)
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        return _skill_result(
            task_id=task_id,
            trace_id=trace_id,
            status="failed",
            code="skill_unavailable",
            message="Vision Service did not accept the target selection request",
            details={"error": str(error)},
        )

    accepted = bool(response.get("accepted"))
    return _skill_result(
        task_id=task_id,
        trace_id=trace_id,
        status="completed" if accepted else "interrupted",
        code="target_selected" if accepted else "target_lost",
        message="Vision target state updated" if accepted else "Vision target state was not updated",
        output={"response": response, "robotControlEnabled": False},
    )


if __name__ == "__main__":
    import sys

    data = json.loads(sys.stdin.read() or "{}")
    operation = data.get("operation", "status")
    result = status() if operation == "status" else invoke(data)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
