"""
FastAPI HTTP service for the ThirdHand Policy module.

Transport is ``http_json`` per the contract. The endpoint path is fixed here but
the host/port come from environment variables (never hard-coded):

* ``THIRDHAND_POLICY_ENDPOINT`` -- base URL advertised to the orchestrator.
* ``THIRDHAND_POLICY_CHECKPOINT`` -- ACT checkpoint dir (enables ``lerobot_act``).
* ``THIRDHAND_POLICY_ARTIFACT_DIR`` -- frames/states store keyed by frameId/robotStateRef.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .handler import handle_policy_action_request

LOG = logging.getLogger(__name__)

app = FastAPI(title="ThirdHand Policy", version="1.0.0")


def load_config() -> dict:
    """Read service configuration from environment variables."""
    return {
        "checkpoint": os.environ.get("THIRDHAND_POLICY_CHECKPOINT"),
        "artifact_dir": os.environ.get("THIRDHAND_POLICY_ARTIFACT_DIR"),
        "device": os.environ.get("THIRDHAND_POLICY_DEVICE", "cpu"),
        "dt_ms": int(os.environ.get("THIRDHAND_POLICY_DT_MS", "100")),
        "fake_steps": int(os.environ.get("THIRDHAND_POLICY_FAKE_STEPS", "3")),
        "enable_fake": os.environ.get("THIRDHAND_POLICY_ENABLE_FAKE", "1") != "0",
        # act_chunk is only offered once the Robot module registers the
        # startouch_action_chunk_adapter_v1 adapter (not yet delivered).
        "act_chunk_adapter_available": (
            os.environ.get("THIRDHAND_POLICY_ACT_CHUNK_ADAPTER_AVAILABLE", "0") == "1"
        ),
    }


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "policy"}


@app.post("/v1/policy/action")
async def policy_action(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"error": "request body must be valid JSON"})

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "request body must be a JSON object"})

    result = handle_policy_action_request(body, load_config())
    # The contract carries success/failure in the message `status` field, so a
    # well-formed policy message is always returned with HTTP 200.
    return JSONResponse(status_code=200, content=result)
