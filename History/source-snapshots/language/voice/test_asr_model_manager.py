#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import unittest
from typing import Any

from asr_model_manager import (
    DEFAULT_MODEL_ID,
    ModelBusyError,
    ModelManager,
    ModelSwitchError,
    ModelState,
)


class FakeBackend:
    def __init__(
        self,
        model_id: str,
        device: str,
        events: list[str],
        *,
        load_failure: Exception | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.events = events
        self.load_failure = load_failure
        self.streams: set[str] = set()

    async def load(self) -> None:
        self.events.append(f"load:{self.model_id}:{self.device}")
        if self.load_failure is not None:
            raise self.load_failure

    async def unload(self) -> None:
        self.events.append(f"unload:{self.model_id}:{self.device}")

    async def transcribe_final(self, audio: Any) -> dict[str, Any]:
        return {
            "text": str(audio),
            "model_id": self.model_id,
            "device": self.device,
            "is_final": True,
        }

    def start_stream(self, session_id: str) -> None:
        self.events.append(f"start_stream:{self.model_id}:{session_id}")
        self.streams.add(session_id)

    async def push_audio(self, session_id: str, pcm: bytes) -> str | None:
        if self.model_id != "paraformer-streaming":
            return None
        self.events.append(f"push_audio:{session_id}:{len(pcm)}")
        return "实时文字"

    async def finish_stream(self, session_id: str, audio: Any) -> dict[str, Any]:
        self.events.append(f"finish_stream:{self.model_id}:{session_id}")
        self.streams.discard(session_id)
        return {
            "text": "最终文字",
            "model_id": self.model_id,
            "device": self.device,
            "is_final": True,
            "processing_time": 0.01,
        }

    def cancel_stream(self, session_id: str) -> None:
        self.events.append(f"cancel_stream:{self.model_id}:{session_id}")
        self.streams.discard(session_id)


class ModelManagerTests(unittest.IsolatedAsyncioTestCase):
    def factories(
        self,
        events: list[str],
        *,
        failure_plan: dict[str, list[Exception | None]] | None = None,
    ) -> dict[str, Any]:
        plans = {
            model_id: list(failures)
            for model_id, failures in (failure_plan or {}).items()
        }

        def factory(model_id: str, device: str):
            def create() -> FakeBackend:
                failures = plans.get(model_id, [])
                load_failure = failures.pop(0) if failures else None
                return FakeBackend(
                    model_id,
                    device,
                    events,
                    load_failure=load_failure,
                )

            return create

        return {
            "whisper-small": factory("whisper-small", "cuda"),
            "fun-asr-nano": factory("fun-asr-nano", "cuda"),
            "paraformer-streaming": factory("paraformer-streaming", "cpu"),
        }

    async def test_every_start_loads_medium_whisper_on_gpu_without_persisted_selection(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))

        status = await manager.start_default()

        self.assertEqual(DEFAULT_MODEL_ID, "whisper-small")
        self.assertEqual(status["state"], ModelState.READY.value)
        self.assertEqual(status["activeModelId"], "whisper-small")
        self.assertEqual(status["device"], "cuda")
        self.assertEqual(events, ["load:whisper-small:cuda"])

    async def test_selecting_active_model_is_a_no_op(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))
        await manager.start_default()

        status = await manager.switch("whisper-small")

        self.assertEqual(status["activeModelId"], "whisper-small")
        self.assertEqual(events, ["load:whisper-small:cuda"])

    async def test_any_active_recording_blocks_the_global_switch(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))
        await manager.start_default()
        manager.begin_recording("browser-a")

        with self.assertRaisesRegex(ModelBusyError, "recording"):
            await manager.switch("paraformer-streaming")

        self.assertEqual(manager.status()["activeModelId"], "whisper-small")
        self.assertEqual(events, [
            "load:whisper-small:cuda",
            "start_stream:whisper-small:browser-a",
        ])

    async def test_concurrent_global_switch_is_rejected_not_queued(self) -> None:
        events: list[str] = []
        release = asyncio.Event()

        class SlowBackend(FakeBackend):
            async def load(self) -> None:
                self.events.append(f"load:{self.model_id}:{self.device}")
                await release.wait()

        factories = self.factories(events)
        factories["paraformer-streaming"] = lambda: SlowBackend(
            "paraformer-streaming", "cpu", events
        )
        manager = ModelManager(factories)
        await manager.start_default()

        first = asyncio.create_task(manager.switch("paraformer-streaming"))
        await asyncio.sleep(0)
        self.assertEqual(manager.status()["state"], ModelState.SWITCHING.value)
        with self.assertRaisesRegex(ModelBusyError, "switch"):
            await manager.switch("fun-asr-nano")

        release.set()
        status = await first
        self.assertEqual(status["activeModelId"], "paraformer-streaming")

    async def test_successful_switch_releases_old_backend_before_loading_target(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))
        await manager.start_default()

        status = await manager.switch("paraformer-streaming")

        self.assertEqual(status["state"], ModelState.READY.value)
        self.assertEqual(status["activeModelId"], "paraformer-streaming")
        self.assertEqual(status["device"], "cpu")
        self.assertEqual(events, [
            "load:whisper-small:cuda",
            "unload:whisper-small:cuda",
            "load:paraformer-streaming:cpu",
        ])

    async def test_failed_switch_restores_previous_model_sequentially(self) -> None:
        events: list[str] = []
        manager = ModelManager(
            self.factories(events, failure_plan={
                "fun-asr-nano": [RuntimeError("out of memory")],
            })
        )
        await manager.start_default()

        with self.assertRaises(ModelSwitchError) as caught:
            await manager.switch("fun-asr-nano")

        status = manager.status()
        self.assertEqual(caught.exception.requested_model_id, "fun-asr-nano")
        self.assertEqual(caught.exception.restored_model_id, "whisper-small")
        self.assertEqual(status["state"], ModelState.READY.value)
        self.assertEqual(status["activeModelId"], "whisper-small")
        self.assertEqual(status["device"], "cuda")
        self.assertIsNone(status["error"])
        self.assertEqual(events, [
            "load:whisper-small:cuda",
            "unload:whisper-small:cuda",
            "load:fun-asr-nano:cuda",
            "unload:fun-asr-nano:cuda",
            "load:whisper-small:cuda",
        ])

    async def test_failed_previous_recovery_falls_back_to_medium(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events, failure_plan={
            "paraformer-streaming": [
                None,
                RuntimeError("paraformer recovery failed"),
            ],
            "fun-asr-nano": [RuntimeError("nano load failed")],
        }))
        await manager.start_default()
        await manager.switch("paraformer-streaming")

        with self.assertRaises(ModelSwitchError) as caught:
            await manager.switch("fun-asr-nano")

        self.assertEqual(caught.exception.restored_model_id, "whisper-small")
        self.assertEqual(manager.status()["state"], ModelState.READY.value)
        self.assertEqual(manager.status()["activeModelId"], "whisper-small")
        self.assertEqual(events, [
            "load:whisper-small:cuda",
            "unload:whisper-small:cuda",
            "load:paraformer-streaming:cpu",
            "unload:paraformer-streaming:cpu",
            "load:fun-asr-nano:cuda",
            "unload:fun-asr-nano:cuda",
            "load:paraformer-streaming:cpu",
            "unload:paraformer-streaming:cpu",
            "load:whisper-small:cuda",
        ])

    async def test_all_recovery_failures_leave_terminal_error(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events, failure_plan={
            "whisper-small": [
                None,
                RuntimeError("medium recovery failed"),
            ],
            "paraformer-streaming": [
                None,
                RuntimeError("paraformer recovery failed"),
            ],
            "fun-asr-nano": [RuntimeError("nano load failed")],
        }))
        await manager.start_default()
        await manager.switch("paraformer-streaming")

        with self.assertRaises(ModelSwitchError) as caught:
            await manager.switch("fun-asr-nano")

        status = manager.status()
        self.assertIsNone(caught.exception.restored_model_id)
        self.assertEqual(status["state"], ModelState.ERROR.value)
        self.assertIsNone(status["activeModelId"])
        self.assertIsNone(status["device"])
        self.assertIn("nano load failed", status["error"])
        with self.assertRaisesRegex(RuntimeError, "No ASR model is ready"):
            manager.begin_recording("blocked")

    async def test_streaming_partial_and_final_use_the_same_active_backend(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))
        await manager.start_default()
        await manager.switch("paraformer-streaming")
        manager.begin_recording("session-1")

        partial = await manager.push_audio("session-1", b"pcm")
        final = await manager.transcribe_final("unused", session_id="session-1")
        manager.end_recording("session-1")

        self.assertEqual(partial, "实时文字")
        self.assertEqual(final["text"], "最终文字")
        self.assertEqual(final["model_id"], "paraformer-streaming")
        self.assertEqual(manager.status()["lastLatencyMs"], 10.0)
        self.assertIn("start_stream:paraformer-streaming:session-1", events)
        self.assertIn("finish_stream:paraformer-streaming:session-1", events)

    async def test_cancelled_recording_clears_stream_state(self) -> None:
        events: list[str] = []
        manager = ModelManager(self.factories(events))
        await manager.start_default()
        manager.begin_recording("session-2")

        manager.cancel_recording("session-2")

        self.assertEqual(manager.status()["recordingCount"], 0)
        self.assertIn("cancel_stream:whisper-small:session-2", events)


if __name__ == "__main__":
    unittest.main()
