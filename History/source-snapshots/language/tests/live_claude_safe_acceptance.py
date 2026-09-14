#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from websockets.asyncio.client import connect


ENDPOINT = os.environ.get("VOICE_ENDPOINT", "ws://127.0.0.1:3004/v1/voice")
SUBPROTOCOL = "thirdhand.voice.v1"


async def main() -> None:
    session_id = f"acceptance-claude-safe-{uuid.uuid4()}"
    request = {
        "v": 1,
        "type": "text.submit",
        "messageId": str(uuid.uuid4()),
        "sessionId": session_id,
        "ts": int(time.time() * 1000),
        "payload": {
            "text": "你好，请用一句话介绍你能做什么。不要控制任何设备，也不要调用任何工具。",
        },
    }
    received_types: list[str] = []
    assistant_responses: list[str] = []
    async with connect(ENDPOINT, subprotocols=[SUBPROTOCOL]) as websocket:
        await websocket.send(json.dumps(request, ensure_ascii=False))
        async with asyncio.timeout(70):
            while True:
                message = json.loads(await websocket.recv())
                message_type = message["type"]
                received_types.append(message_type)
                if message_type == "error":
                    raise AssertionError(message["payload"])
                if message_type == "assistant.response":
                    assistant_responses.append(
                        str(message["payload"].get("text") or "").strip()
                    )
                if message_type == "session.completed":
                    break

    response = "\n".join(item for item in assistant_responses if item)
    assert response
    lowered = response.lower()
    assert "authentication_error" not in lowered
    assert "invalid x-api-key" not in lowered
    assert "could not resolve authentication method" not in lowered
    assert "api 错误" not in lowered
    assert "intent.candidate" not in received_types
    assert "confirmation.decision" not in received_types
    assert "execution.result" not in received_types
    print(json.dumps({
        "ok": True,
        "receivedTypes": received_types,
        "assistantResponse": response,
        "candidateSent": False,
        "confirmationSent": False,
        "motionRequested": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
