#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from typing import Any


def validate_ready_payload(message: dict[str, Any]) -> list[str]:
    status = message.get("payload", {}).get("status", {})
    errors: list[str] = []
    if status.get("state") != "READY":
        errors.append(f"ASR_STATE:{status.get('state')}")
    if status.get("activeModelId") != "whisper-small":
        errors.append(f"ASR_MODEL:{status.get('activeModelId')}")
    if status.get("device") != "cuda":
        errors.append(f"ASR_DEVICE:{status.get('device')}")
    return errors


async def check(endpoint: str, timeout: float) -> dict[str, Any]:
    from websockets.asyncio.client import connect

    request = json.dumps({
        "v": 1,
        "type": "model.list",
        "messageId": str(uuid.uuid4()),
        "sessionId": None,
        "ts": int(time.time() * 1000),
        "payload": {},
    })
    async with asyncio.timeout(timeout):
        async with connect(
            endpoint,
            subprotocols=["thirdhand.voice.v1"],
        ) as websocket:
            await websocket.send(request)
            message = json.loads(await websocket.recv())
    errors = validate_ready_payload(message)
    return {"ok": not errors, "errors": errors, "message": message}


def main() -> int:
    parser = argparse.ArgumentParser(description="Require default Whisper Small/cuda readiness.")
    parser.add_argument("--endpoint", default="ws://127.0.0.1:3004/v1/voice")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    try:
        result = asyncio.run(check(args.endpoint, args.timeout))
    except Exception as error:
        result = {
            "ok": False,
            "errors": [f"VOICE_UNREACHABLE:{type(error).__name__}"],
            "message": str(error),
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
