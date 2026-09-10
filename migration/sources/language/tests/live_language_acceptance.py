#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import time
import uuid

from websockets.asyncio.client import connect


async def main() -> None:
    session_id = "acceptance-intent-candidate"
    request = {
        "v": 1,
        "type": "text.submit",
        "messageId": str(uuid.uuid4()),
        "sessionId": session_id,
        "ts": int(time.time() * 1000),
        "payload": {"text": "请将机械臂向左转动十度"},
    }
    received_types: list[str] = []
    assistant_responses: list[str] = []
    candidate = None
    async with connect(
        "ws://127.0.0.1:3004/v1/voice",
        subprotocols=["thirdhand.voice.v1"],
    ) as websocket:
        await websocket.send(json.dumps(request, ensure_ascii=False))
        async with asyncio.timeout(70):
            while candidate is None:
                message = json.loads(await websocket.recv())
                message_type = message["type"]
                received_types.append(message_type)
                if message_type == "error":
                    raise AssertionError(message["payload"])
                if message_type == "assistant.response":
                    assistant_responses.append(str(message["payload"].get("text") or ""))
                if message_type == "intent.candidate":
                    candidate = message["payload"]
                elif message_type == "session.completed" and candidate is None:
                    raise AssertionError({
                        "reason": "session completed without intent.candidate",
                        "payload": message["payload"],
                        "assistantResponses": assistant_responses,
                    })

    assert candidate is not None
    assert candidate.get("candidateId")
    assert "confirmation.decision" not in received_types
    assert "execution.result" not in received_types
    print(json.dumps({
        "ok": True,
        "receivedTypes": received_types,
        "candidate": candidate,
        "candidateActionSent": False,
        "confirmationSent": False,
        "motionRequested": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
