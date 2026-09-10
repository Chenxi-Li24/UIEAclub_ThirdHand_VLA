#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import struct
import time
import uuid
import wave

from websockets.asyncio.client import connect


ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = os.environ.get("VOICE_ENDPOINT", "ws://127.0.0.1:3004/v1/voice")
SUBPROTOCOL = "thirdhand.voice.v1"
FRAME_BYTES = 3_200


def envelope(message_type: str, session_id: str | None = None, payload=None) -> str:
    return json.dumps({
        "v": 1,
        "type": message_type,
        "messageId": str(uuid.uuid4()),
        "sessionId": session_id,
        "ts": int(time.time() * 1000),
        "payload": payload or {},
    }, ensure_ascii=False)


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as source:
        assert source.getframerate() == 16_000
        assert source.getnchannels() == 1
        assert source.getsampwidth() == 2
        return source.readframes(source.getnframes())


async def receive_until(websocket, predicate, timeout: float = 75.0):
    messages = []
    async with asyncio.timeout(timeout):
        while True:
            message = json.loads(await websocket.recv())
            messages.append(message)
            if message["type"] == "error":
                raise AssertionError(message["payload"])
            if predicate(message):
                return message, messages


async def switch_model(model_id: str):
    async with connect(ENDPOINT, subprotocols=[SUBPROTOCOL]) as websocket:
        await websocket.send(envelope("model.select", payload={"modelId": model_id}))
        ready, _ = await receive_until(
            websocket,
            lambda item: item["type"] == "model.status"
            and item["payload"]["state"] == "READY",
        )
        assert ready["payload"]["activeModelId"] == model_id
        return ready["payload"]


async def transcribe(path: Path, *, expect_partial: bool):
    pcm = read_pcm(path)
    session_id = f"acceptance-audio-{uuid.uuid4()}"
    async with connect(ENDPOINT, subprotocols=[SUBPROTOCOL]) as websocket:
        await websocket.send(envelope("session.start", session_id, {
            "audio": {
                "encoding": "pcm_s16le",
                "sampleRate": 16_000,
                "channels": 1,
                "frameMs": 100,
            },
        }))
        await receive_until(websocket, lambda item: item["type"] == "session.ready")
        for sequence, offset in enumerate(range(0, len(pcm), FRAME_BYTES)):
            chunk = pcm[offset: offset + FRAME_BYTES].ljust(FRAME_BYTES, b"\0")
            await websocket.send(
                struct.pack("<4sII", b"THV1", sequence, sequence * 100) + chunk
            )
        await websocket.send(envelope("session.stop", session_id))
        final, messages = await receive_until(
            websocket, lambda item: item["type"] == "transcript.final"
        )
    partials = [
        item["payload"]["text"] for item in messages
        if item["type"] == "transcript.partial"
    ]
    assert bool(partials) is expect_partial
    assert "confirmation.decision" not in [item["type"] for item in messages]
    assert "execution.result" not in [item["type"] for item in messages]
    return {"text": final["payload"]["text"], "partials": partials}


async def main() -> None:
    whisper = await transcribe(
        ROOT / "benchmarks" / "audio" / "official-nano-en.wav",
        expect_partial=False,
    )
    assert whisper["text"].strip()

    para_status = await switch_model("paraformer-streaming")
    assert para_status["device"] == "cpu"
    para = await transcribe(
        ROOT / "benchmarks" / "audio" / "official-nano-zh.wav",
        expect_partial=True,
    )
    assert para["text"].strip()

    fun_status = await switch_model("fun-asr-nano")
    assert fun_status["device"] == "cuda"
    fun_asr = await transcribe(
        ROOT / "benchmarks" / "audio" / "official-nano-zh.wav",
        expect_partial=False,
    )
    assert fun_asr["text"].strip()

    final_status = await switch_model("whisper-small")
    assert final_status["device"] == "cuda"
    print(json.dumps({
        "ok": True,
        "whisperSmallEnglish": whisper["text"],
        "paraformerCpuChinese": para["text"],
        "paraformerPartialCount": len(para["partials"]),
        "funAsrNanoChinese": fun_asr["text"],
        "finalActiveModel": "whisper-small",
        "confirmationSent": False,
        "motionRequested": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
