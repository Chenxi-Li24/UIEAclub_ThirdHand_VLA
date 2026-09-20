"""Opt-in, supervised test for the complete local VA service."""

from __future__ import annotations

import json
import os
import time
from uuid import uuid4
from urllib.request import Request, urlopen

import pytest


pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("THIRDHAND_LIVE_TEST") == "1"
        and os.environ.get("THIRDHAND_ALLOW_ROBOT")
        == "I_ACCEPT_SUPERVISED_ROBOT_MOTION"
    ),
    reason="requires exact supervised live-robot authorization",
)


def test_live_va_skill_accepts_one_requested_stable_id() -> None:
    base_url = os.environ.get("THIRDHAND_VA_URL", "http://127.0.0.1:8766")
    request_id = f"pytest-supervised-live-{uuid4()}"
    body = json.dumps(
        {
            "schema": "thirdhand.va.command.v1",
            "cmd": "start",
            "target_id": 1,
            "request_id": request_id,
        }
    ).encode()
    request = Request(
        f"{base_url}/api/va/start",
        data=body,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        payload = json.load(response)

    assert response.status == 202
    assert payload["accepted"] is True
    assert payload["target_id"] == 1
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        with urlopen(f"{base_url}/api/va/status", timeout=5) as status_response:
            status = json.load(status_response)
        if status.get("active") is not True:
            result = status.get("last_result") or {}
            assert result.get("requestId") == request_id
            assert result.get("targetId") == 1
            assert result.get("ok") is True
            assert result.get("phase") == "complete"
            return
        time.sleep(0.5)
    stop = Request(
        f"{base_url}/api/va/stop",
        data=json.dumps(
            {
                "schema": "thirdhand.va.command.v1",
                "cmd": "stop",
                "request_id": f"pytest-timeout-stop-{uuid4()}",
            }
        ).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(stop, timeout=5):
            pass
    except OSError:
        pass
    pytest.fail("live VA workflow did not reach complete within 300 seconds")
