#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from typing import Any

from websockets.asyncio.client import connect

from asr_model_manager import ModelManager
from test_voice_bridge import (
    FakeClaude,
    audio_frame,
    envelope,
    receive_json,
    receive_through,
    running_bridge,
    start_message,
)
from voice_bridge import VoiceBridge, WEBSOCKET_SUBPROTOCOL


class ProtocolBackend:
    def __init__(
        self,
        model_id: str,
        device: str,
        *,
        load_failure: Exception | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.load_failure = load_failure
        self.streams: set[str] = set()

    async def load(self) -> None:
        if self.load_failure is not None:
            raise self.load_failure
        return None

    async def unload(self) -> None:
        self.streams.clear()

    def start_stream(self, session_id: str) -> None:
        self.streams.add(session_id)

    async def push_audio(self, session_id: str, _pcm: bytes) -> str | None:
        if self.model_id == "paraformer-streaming":
            return "向左"
        return None

    async def finish_stream(self, session_id: str, _audio: Any) -> dict[str, Any]:
        self.streams.discard(session_id)
        return {
            "text": "向左一点",
            "language": "zh",
            "duration": 0.1,
            "processing_time": 0.01,
            "model_id": self.model_id,
            "device": self.device,
            "is_final": True,
        }

    async def transcribe_final(self, _audio: Any) -> dict[str, Any]:
        return {
            "text": "向左一点",
            "language": "zh",
            "duration": 0.1,
            "processing_time": 0.01,
            "model_id": self.model_id,
            "device": self.device,
            "is_final": True,
        }

    def cancel_stream(self, session_id: str) -> None:
        self.streams.discard(session_id)


async def create_manager(
    failure_plan: dict[str, list[Exception | None]] | None = None,
) -> ModelManager:
    plans = {
        model_id: list(failures)
        for model_id, failures in (failure_plan or {}).items()
    }

    def factory(model_id: str, device: str):
        def create() -> ProtocolBackend:
            failures = plans.get(model_id, [])
            failure = failures.pop(0) if failures else None
            return ProtocolBackend(
                model_id,
                device,
                load_failure=failure,
            )

        return create

    manager = ModelManager({
        "whisper-small": factory("whisper-small", "cuda"),
        "fun-asr-nano": factory("fun-asr-nano", "cuda"),
        "paraformer-streaming": factory("paraformer-streaming", "cpu"),
    })
    await manager.start_default()
    return manager


class AsrV2ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_list_exposes_three_approved_models(self) -> None:
        manager = await create_manager()
        bridge = VoiceBridge(None, lambda: FakeClaude(), model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as websocket:
                request = envelope("model.list", None)
                await websocket.send(request)
                response = await receive_json(websocket)

        self.assertEqual(response["type"], "model.list")
        self.assertEqual(response["payload"]["models"], [
            {
                "modelId": "whisper-small",
                "label": "Medium",
                "technicalName": "Whisper Small",
                "description": "默认中英文整句识别，使用本地 Whisper Small。",
                "device": "cuda",
                "streaming": False,
                "experimental": False,
            },
            {
                "modelId": "paraformer-streaming",
                "label": "Real-time",
                "technicalName": "Paraformer CPU",
                "description": "中文流式识别，使用 CPU 并降低 GPU 占用。",
                "device": "cpu",
                "streaming": True,
                "experimental": False,
            },
            {
                "modelId": "fun-asr-nano",
                "label": "High",
                "technicalName": "Fun-ASR-Nano",
                "description": "实验模型，使用 Fun-ASR-Nano 并占用较高 GPU 显存。",
                "device": "cuda",
                "streaming": False,
                "experimental": True,
            },
        ])
        self.assertEqual(response["payload"]["status"]["activeModelId"], "whisper-small")
        self.assertEqual(response["payload"]["status"]["recordingCount"], 0)

    async def test_model_switch_is_global_and_broadcast_to_every_client(self) -> None:
        manager = await create_manager()
        bridge = VoiceBridge(None, lambda: FakeClaude(), model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as first:
                async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as second:
                    await first.send(envelope(
                        "model.select", None, {"modelId": "paraformer-streaming"}
                    ))
                    first_switching = await receive_json(first)
                    second_switching = await receive_json(second)
                    first_status = await receive_json(first)
                    second_status = await receive_json(second)

        self.assertEqual(first_switching["type"], "model.status")
        self.assertEqual(second_switching["type"], "model.status")
        self.assertEqual(first_switching["payload"]["state"], "SWITCHING")
        self.assertEqual(first_switching["payload"], second_switching["payload"])
        self.assertEqual(first_status["type"], "model.status")
        self.assertEqual(second_status["type"], "model.status")
        self.assertEqual(first_status["payload"], second_status["payload"])
        self.assertEqual(first_status["payload"]["activeModelId"], "paraformer-streaming")
        self.assertEqual(first_status["payload"]["device"], "cpu")

    async def test_failed_switch_reports_recovery_and_broadcasts_restored_model(self) -> None:
        manager = await create_manager({
            "fun-asr-nano": [RuntimeError("out of memory")],
        })
        bridge = VoiceBridge(None, lambda: FakeClaude(), model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as first:
                async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as second:
                    await first.send(envelope(
                        "model.select", None, {"modelId": "fun-asr-nano"}
                    ))
                    first_switching = await receive_json(first)
                    second_switching = await receive_json(second)
                    first_restored = await receive_json(first)
                    second_restored = await receive_json(second)
                    error = await receive_json(first)

        self.assertEqual(first_switching["payload"]["state"], "SWITCHING")
        self.assertEqual(first_switching["payload"], second_switching["payload"])
        self.assertEqual(first_restored["type"], "model.status")
        self.assertEqual(first_restored["payload"], second_restored["payload"])
        self.assertEqual(first_restored["payload"]["state"], "READY")
        self.assertEqual(first_restored["payload"]["activeModelId"], "whisper-small")
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["payload"]["code"], "MODEL_SWITCH_FAILED")
        self.assertTrue(error["payload"]["recoverable"])
        self.assertEqual(error["payload"]["requestedModelId"], "fun-asr-nano")
        self.assertEqual(error["payload"]["restoredModelId"], "whisper-small")

    async def test_recording_blocks_model_switch_for_all_clients(self) -> None:
        manager = await create_manager()
        bridge = VoiceBridge(None, lambda: FakeClaude(), model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as recorder:
                async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as switcher:
                    await recorder.send(start_message("recording-1"))
                    ready = await receive_json(recorder)
                    recorder_active = await receive_json(recorder)
                    switcher_active = await receive_json(switcher)
                    await switcher.send(envelope(
                        "model.select", None, {"modelId": "paraformer-streaming"}
                    ))
                    error = await receive_json(switcher)
                    await recorder.send(envelope(
                        "session.cancel", "recording-1", {"reason": "test_done"}
                    ))
                    cancelled = await receive_json(recorder)
                    recorder_idle = await receive_json(recorder)
                    switcher_idle = await receive_json(switcher)

        self.assertEqual(ready["type"], "session.ready")
        self.assertEqual(recorder_active["type"], "model.status")
        self.assertEqual(recorder_active["payload"]["recordingCount"], 1)
        self.assertEqual(recorder_active["payload"], switcher_active["payload"])
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["payload"]["code"], "MODEL_BUSY")
        self.assertEqual(cancelled["type"], "session.cancelled")
        self.assertEqual(recorder_idle["payload"]["recordingCount"], 0)
        self.assertEqual(recorder_idle["payload"], switcher_idle["payload"])
        self.assertEqual(manager.status()["activeModelId"], "whisper-small")

    async def test_disconnect_broadcasts_recording_count_zero(self) -> None:
        manager = await create_manager()
        bridge = VoiceBridge(None, lambda: FakeClaude(), model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as observer:
                async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as recorder:
                    await recorder.send(start_message("disconnect-1"))
                    self.assertEqual((await receive_json(recorder))["type"], "session.ready")
                    recorder_active = await receive_json(recorder)
                    observer_active = await receive_json(observer)
                    self.assertEqual(recorder_active["payload"]["recordingCount"], 1)
                    self.assertEqual(recorder_active["payload"], observer_active["payload"])

                observer_idle = await receive_json(observer)

        self.assertEqual(observer_idle["type"], "model.status")
        self.assertEqual(observer_idle["payload"]["recordingCount"], 0)

    async def test_partial_is_display_only_and_final_reaches_claude_once(self) -> None:
        manager = await create_manager()
        await manager.switch("paraformer-streaming")
        claude = FakeClaude()
        bridge = VoiceBridge(None, lambda: claude, model_manager=manager)

        async with running_bridge(bridge) as url:
            async with connect(url, subprotocols=[WEBSOCKET_SUBPROTOCOL]) as websocket:
                await websocket.send(start_message("stream-1"))
                self.assertEqual((await receive_json(websocket))["type"], "session.ready")
                recording_status = await receive_json(websocket)
                self.assertEqual(recording_status["type"], "model.status")
                self.assertEqual(recording_status["payload"]["recordingCount"], 1)
                await websocket.send(audio_frame(0, sample=1000))
                partial = await receive_json(websocket)
                await websocket.send(envelope("session.stop", "stream-1"))
                completed = await receive_through(websocket, "session.completed")

        self.assertEqual(partial["type"], "transcript.partial")
        self.assertEqual(partial["payload"]["text"], "向左")
        final = next(message for message in completed if message["type"] == "transcript.final")
        model_status = next(
            message for message in completed if message["type"] == "model.status"
        )
        self.assertEqual(model_status["payload"]["lastLatencyMs"], 10.0)
        self.assertEqual(final["payload"]["text"], "向左一点")
        self.assertEqual(claude.inputs, ["向左一点"])
        self.assertIn("intent.candidate", [message["type"] for message in completed])
        self.assertNotIn("confirmation.decision", [message["type"] for message in completed])


if __name__ == "__main__":
    unittest.main()
