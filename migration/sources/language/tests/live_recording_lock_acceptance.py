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


def envelope(message_type: str, session_id: str | None = None, payload=None) -> str:
    return json.dumps({
        "v": 1,
        "type": message_type,
        "messageId": str(uuid.uuid4()),
        "sessionId": session_id,
        "ts": int(time.time() * 1000),
        "payload": payload or {},
    }, ensure_ascii=False)


async def receive_until(websocket, predicate, timeout: float = 75.0):
    async with asyncio.timeout(timeout):
        while True:
            message = json.loads(await websocket.recv())
            if predicate(message):
                return message


async def main() -> None:
    async with connect(ENDPOINT, subprotocols=[SUBPROTOCOL]) as recorder:
        async with connect(ENDPOINT, subprotocols=[SUBPROTOCOL]) as switcher:
            await switcher.send(envelope("model.select", payload={
                "modelId": "whisper-small",
            }))
            await receive_until(
                switcher,
                lambda item: item["type"] == "model.status"
                and item["payload"]["state"] == "READY"
                and item["payload"]["activeModelId"] == "whisper-small",
            )
            await recorder.send(envelope("model.list"))
            listing = await receive_until(
                recorder, lambda item: item["type"] == "model.list"
            )
            models = listing["payload"]["models"]
            status = listing["payload"]["status"]
            assert [(item["modelId"], item["device"]) for item in models] == [
                ("whisper-small", "cuda"),
                ("paraformer-streaming", "cpu"),
                ("fun-asr-nano", "cuda"),
            ]
            assert status["state"] == "READY"
            assert status["activeModelId"] == "whisper-small"

            session_id = f"acceptance-record-lock-{uuid.uuid4()}"
            await recorder.send(envelope("session.start", session_id, {
                "audio": {
                    "encoding": "pcm_s16le",
                    "sampleRate": 16_000,
                    "channels": 1,
                    "frameMs": 100,
                },
            }))
            await receive_until(recorder, lambda item: item["type"] == "session.ready")
            await switcher.send(envelope("model.select", payload={
                "modelId": "fun-asr-nano",
            }))
            busy = await receive_until(switcher, lambda item: item["type"] == "error")
            assert busy["payload"]["code"] == "MODEL_BUSY"

            await recorder.send(envelope("session.cancel", session_id, {
                "reason": "acceptance_complete",
            }))
            await receive_until(
                recorder, lambda item: item["type"] == "session.cancelled"
            )

            await switcher.send(envelope("model.select", payload={
                "modelId": "paraformer-streaming",
            }))
            para_ready = await receive_until(
                switcher,
                lambda item: item["type"] == "model.status"
                and item["payload"]["state"] == "READY"
                and item["payload"]["activeModelId"] == "paraformer-streaming",
            )
            assert para_ready["payload"]["activeModelId"] == "paraformer-streaming"
            assert para_ready["payload"]["device"] == "cpu"

            await switcher.send(envelope("model.select", payload={
                "modelId": "whisper-small",
            }))
            final_ready = await receive_until(
                switcher,
                lambda item: item["type"] == "model.status"
                and item["payload"]["state"] == "READY"
                and item["payload"]["activeModelId"] == "whisper-small",
            )
            assert final_ready["payload"]["activeModelId"] == "whisper-small"
            assert final_ready["payload"]["device"] == "cuda"

    print(json.dumps({
        "ok": True,
        "defaultModel": "whisper-small",
        "recordingSwitchError": "MODEL_BUSY",
        "postRecordingSwitch": "paraformer-streaming",
        "finalActiveModel": "whisper-small",
        "confirmationSent": False,
        "motionRequested": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
