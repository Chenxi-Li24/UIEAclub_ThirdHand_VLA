#!/usr/bin/env python3
"""Protocol and safety tests for voice_bridge.py.

The tests use fake ASR and Claude implementations. They exercise a real local
WebSocket server, but never load a model or connect to robot-control software.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import socket
import struct
import threading
import unittest
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve
except ImportError:  # websockets <= 13
    from websockets import connect, serve

from voice_bridge import (
    AUDIO_FRAME_PCM_BYTES,
    AUDIO_MAGIC,
    MAX_TEXT_INPUT_CHARS,
    MAX_WEBSOCKET_MESSAGE_BYTES,
    VoiceBridge,
    WEBSOCKET_PATH,
    WEBSOCKET_SUBPROTOCOL,
)


def envelope(
    message_type: str,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
) -> str:
    return json.dumps(
        {
            "v": 1,
            "type": message_type,
            "messageId": str(uuid.uuid4()),
            "replyTo": None,
            "sessionId": session_id,
            "ts": 1,
            "payload": payload or {},
        }
    )


def start_message(session_id: str) -> str:
    return envelope(
        "session.start",
        session_id,
        {
            "audio": {
                "encoding": "pcm_s16le",
                "sampleRate": 16_000,
                "channels": 1,
                "frameMs": 100,
            }
        },
    )


def text_message(session_id: str | None, text: Any) -> str:
    return envelope("text.submit", session_id, {"text": text})


def audio_frame(
    sequence: int,
    *,
    elapsed_ms: int | None = None,
    magic: bytes = AUDIO_MAGIC,
    sample: int = 0,
) -> bytes:
    if elapsed_ms is None:
        elapsed_ms = sequence * 100
    header = magic + struct.pack("<II", sequence, elapsed_ms)
    pcm = struct.pack("<h", sample) * (AUDIO_FRAME_PCM_BYTES // 2)
    return header + pcm


async def receive_json(websocket: Any, timeout: float = 2.0) -> dict[str, Any]:
    incoming = await asyncio.wait_for(websocket.recv(), timeout)
    if not isinstance(incoming, str):
        raise AssertionError("Bridge returned unexpected binary data")
    return json.loads(incoming)


async def receive_through(
    websocket: Any,
    terminal_type: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for _ in range(limit):
        message = await receive_json(websocket)
        messages.append(message)
        if message["type"] == terminal_type:
            return messages
    raise AssertionError(f"Did not receive {terminal_type} within {limit} messages")


@asynccontextmanager
async def running_bridge(bridge: VoiceBridge, *, port: int = 0):
    async with serve(
        bridge.handle_connection,
        "127.0.0.1",
        port,
        subprotocols=[WEBSOCKET_SUBPROTOCOL],
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        compression=None,
        ping_interval=None,
    ) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}{WEBSOCKET_PATH}"


class FakeASR:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.sample_counts: list[int] = []

    def transcribe(self, audio: Any) -> dict[str, Any]:
        self.sample_counts.append(len(audio))
        if self.failure is not None:
            raise self.failure
        return {
            "text": f"识别到 {len(audio)} 个采样",
            "language": "zh",
            "duration": len(audio) / 16_000,
            "language_prob": 0.99,
        }


class FakeClaude:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        entered: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.failure = failure
        self.entered = entered
        self.release = release
        self.inputs: list[str] = []

    def chat(self, text: str) -> dict[str, Any]:
        self.inputs.append(text)
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            self.release.wait(timeout=2)
        if self.failure is not None:
            raise self.failure
        return {
            "text": "好的，我已理解你的指令。",
            "actions": [{"tool": "release", "input": {}}],
        }


class BlockingFirstASR:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.active = 0
        self.max_active = 0
        self.call_count = 0
        self.lock = threading.Lock()

    def transcribe(self, audio: Any) -> dict[str, Any]:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.call_count += 1
            call_number = self.call_count
        try:
            if call_number == 1:
                self.entered.set()
                self.release.wait(timeout=2)
            return {
                "text": f"识别到 {len(audio)} 个采样",
                "language": "zh",
                "duration": len(audio) / 16_000,
                "language_prob": 0.99,
            }
        finally:
            with self.lock:
                self.active -= 1


class VoiceBridgeProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_round_trip_bypasses_asr_and_reuses_claude(self) -> None:
        asr = FakeASR()
        created: list[FakeClaude] = []

        def create_claude() -> FakeClaude:
            agent = FakeClaude()
            created.append(agent)
            return agent

        bridge = VoiceBridge(asr, create_claude)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                first_request = text_message("text-1", "打开夹爪")
                first_message_id = json.loads(first_request)["messageId"]
                await websocket.send(first_request)
                first = await receive_through(websocket, "session.completed")
                second_request = text_message("text-2", "然后松开")
                second_message_id = json.loads(second_request)["messageId"]
                await websocket.send(second_request)
                second = await receive_through(websocket, "session.completed")

        expected_types = [
            "session.processing",
            "assistant.response",
            "intent.candidate",
            "session.completed",
        ]
        self.assertEqual([message["type"] for message in first], expected_types)
        self.assertEqual([message["type"] for message in second], expected_types)
        self.assertEqual(first[0]["payload"]["inputMode"], "text")
        self.assertEqual(first[1]["payload"]["inputMode"], "text")
        self.assertEqual(first[2]["payload"]["sourceText"], "打开夹爪")
        self.assertTrue(first[2]["payload"]["requiresConfirmation"])
        self.assertTrue(
            all(message["replyTo"] == first_message_id for message in first)
        )
        self.assertTrue(
            all(message["replyTo"] == second_message_id for message in second)
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].inputs, ["打开夹爪", "然后松开"])
        self.assertEqual(asr.sample_counts, [])

    async def test_unicode_text_limit_uses_production_websocket_size(self) -> None:
        bridge = VoiceBridge(
            FakeASR(),
            lambda: FakeClaude(),
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(
                    text_message("unicode-limit", "界" * MAX_TEXT_INPUT_CHARS)
                )
                accepted = await receive_through(websocket, "session.completed")
                self.assertEqual(accepted[0]["type"], "session.processing")

                await websocket.send(
                    text_message(
                        "unicode-too-long",
                        "界" * (MAX_TEXT_INPUT_CHARS + 1),
                    )
                )
                rejected = await receive_json(websocket)
                self.assertEqual(rejected["payload"]["code"], "TEXT_TOO_LONG")

    async def test_text_validation_and_audio_exclusivity(self) -> None:
        claude_created = False

        def create_claude() -> FakeClaude:
            nonlocal claude_created
            claude_created = True
            return FakeClaude()

        bridge = VoiceBridge(FakeASR(), create_claude)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("empty", "   "))
                empty = await receive_json(websocket)
                self.assertEqual(empty["payload"]["code"], "BAD_MESSAGE")

                await websocket.send(text_message("not-string", 42))
                not_string = await receive_json(websocket)
                self.assertEqual(not_string["payload"]["code"], "BAD_MESSAGE")

                await websocket.send(
                    text_message("too-long", "x" * (MAX_TEXT_INPUT_CHARS + 1))
                )
                too_long = await receive_json(websocket)
                self.assertEqual(too_long["payload"]["code"], "TEXT_TOO_LONG")

                await websocket.send(text_message(None, "hello"))
                missing_session = await receive_json(websocket)
                self.assertEqual(missing_session["payload"]["code"], "BAD_MESSAGE")

                await websocket.send(start_message("audio-active"))
                self.assertEqual((await receive_json(websocket))["type"], "session.ready")
                await websocket.send(text_message("text-blocked", "hello"))
                blocked = await receive_json(websocket)
                self.assertEqual(blocked["payload"]["code"], "INVALID_STATE")
                await websocket.send(envelope("session.cancel", "audio-active"))
                await receive_json(websocket)

        self.assertFalse(claude_created)

    async def test_text_concurrency_and_cancel_suppress_late_results(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        claude = FakeClaude(entered=entered, release=release)
        bridge = VoiceBridge(
            FakeASR(),
            lambda: claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("text-blocking", "第一条"))
                processing = await receive_json(websocket)
                self.assertEqual(processing["type"], "session.processing")
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))

                await websocket.send(text_message("text-overlap", "第二条"))
                overlap = await receive_json(websocket)
                self.assertEqual(overlap["payload"]["code"], "INVALID_STATE")

                await websocket.send(start_message("audio-overlap"))
                audio_overlap = await receive_json(websocket)
                self.assertEqual(
                    audio_overlap["payload"]["code"],
                    "INVALID_STATE",
                )

                await websocket.send(
                    envelope("session.cancel", "text-blocking", {"reason": "user"})
                )
                cancelled = await receive_json(websocket)
                self.assertEqual(cancelled["type"], "session.cancelled")
                self.assertEqual(cancelled["payload"]["inputMode"], "text")
                release.set()

                with self.assertRaises(asyncio.TimeoutError):
                    await receive_json(websocket, timeout=0.15)

                await websocket.send(text_message("text-after-cancel", "第三条"))
                restarted = await receive_through(websocket, "session.completed")
                self.assertEqual(restarted[0]["type"], "session.processing")

    async def test_cancelled_claude_call_cannot_overlap_immediate_retry(self) -> None:
        first_entered = threading.Event()
        second_entered = threading.Event()
        release_first = threading.Event()
        created: list[FakeClaude] = []

        def create_claude() -> FakeClaude:
            if not created:
                agent = FakeClaude(entered=first_entered, release=release_first)
            else:
                agent = FakeClaude(entered=second_entered)
            created.append(agent)
            return agent

        bridge = VoiceBridge(
            FakeASR(),
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("old-text", "第一条"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                self.assertTrue(await asyncio.to_thread(first_entered.wait, 1))

                await websocket.send(envelope("session.cancel", "old-text"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.cancelled",
                )

                await websocket.send(text_message("new-text", "第二条"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                await asyncio.sleep(0.1)
                self.assertFalse(second_entered.is_set())
                self.assertEqual(len(created), 1)

                release_first.set()
                retried = await receive_through(websocket, "session.completed")

        self.assertTrue(second_entered.is_set())
        self.assertEqual(
            [message["type"] for message in retried],
            ["assistant.response", "intent.candidate", "session.completed"],
        )
        self.assertEqual(len(created), 2)

    async def test_cancel_during_slow_factory_does_not_reuse_retired_agent(self) -> None:
        factory_entered = threading.Event()
        release_factory = threading.Event()
        factory_calls = 0
        created: list[FakeClaude] = []
        factory_lock = threading.Lock()

        def create_claude() -> FakeClaude:
            nonlocal factory_calls
            with factory_lock:
                factory_calls += 1
                call_number = factory_calls
            if call_number == 1:
                factory_entered.set()
                release_factory.wait(timeout=2)
            agent = FakeClaude()
            created.append(agent)
            return agent

        bridge = VoiceBridge(
            FakeASR(),
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("slow-factory-old", "取消这条"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                self.assertTrue(
                    await asyncio.to_thread(factory_entered.wait, 1)
                )

                await websocket.send(
                    envelope("session.cancel", "slow-factory-old")
                )
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.cancelled",
                )

                await websocket.send(text_message("slow-factory-new", "保留这条"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                release_factory.set()
                await receive_through(websocket, "session.completed")

        self.assertEqual(factory_calls, 2)
        self.assertEqual(len(created), 2)
        self.assertEqual(created[0].inputs, [])
        self.assertEqual(created[1].inputs, ["保留这条"])

    async def test_cancelling_recording_preserves_claude_history(self) -> None:
        created: list[FakeClaude] = []

        def create_claude() -> FakeClaude:
            agent = FakeClaude()
            created.append(agent)
            return agent

        bridge = VoiceBridge(
            FakeASR(),
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("history-a", "记住第一条"))
                await receive_through(websocket, "session.completed")

                await websocket.send(start_message("cancel-recording"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.ready",
                )
                await websocket.send(envelope("session.cancel", "cancel-recording"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.cancelled",
                )

                await websocket.send(text_message("history-b", "继续第二条"))
                await receive_through(websocket, "session.completed")

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].inputs, ["记住第一条", "继续第二条"])

    async def test_text_llm_failure_reports_error_and_completes(self) -> None:
        asr = FakeASR()
        attempts = 0

        def create_claude() -> FakeClaude:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return FakeClaude(failure=RuntimeError("CC-Switch offline"))
            return FakeClaude()

        bridge = VoiceBridge(
            asr,
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(text_message("text-failure", "你好"))
                messages = await receive_through(websocket, "session.completed")
                await websocket.send(text_message("text-retry", "再试一次"))
                retried = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "error", "session.completed"],
        )
        self.assertEqual(messages[1]["payload"]["code"], "LLM_UNAVAILABLE")
        self.assertFalse(messages[2]["payload"]["llmAvailable"])
        self.assertEqual(
            [message["type"] for message in retried],
            [
                "session.processing",
                "assistant.response",
                "intent.candidate",
                "session.completed",
            ],
        )
        self.assertEqual(attempts, 2)
        self.assertEqual(asr.sample_counts, [])

    async def test_text_clients_use_separate_claude_instances(self) -> None:
        created: list[FakeClaude] = []

        def create_claude() -> FakeClaude:
            agent = FakeClaude()
            created.append(agent)
            return agent

        bridge = VoiceBridge(
            FakeASR(),
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as client_a:
                async with connect(
                    url,
                    subprotocols=[WEBSOCKET_SUBPROTOCOL],
                ) as client_b:
                    await client_a.send(text_message("text-a", "客户端 A"))
                    await client_b.send(text_message("text-b", "客户端 B"))
                    await asyncio.gather(
                        receive_through(client_a, "session.completed"),
                        receive_through(client_b, "session.completed"),
                    )

        self.assertEqual(len(created), 2)
        self.assertCountEqual(
            [agent.inputs[0] for agent in created],
            ["客户端 A", "客户端 B"],
        )

    async def test_tcp_port_3001_accepts_bridge_protocol(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", 3001))
            except OSError:
                self.skipTest("TCP 3001 is already used by the running frontend mock")

        bridge = VoiceBridge(FakeASR(), None)

        async with running_bridge(bridge, port=3001) as url:
            self.assertEqual(url, "ws://127.0.0.1:3001/v1/voice")
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("port-3001"))
                self.assertEqual((await receive_json(websocket))["type"], "session.ready")
                await websocket.send(audio_frame(0))
                await websocket.send(envelope("session.stop", "port-3001"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )

    async def test_tcp_port_3002_accepts_optimized_final_only_protocol(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", 3002))
            except OSError:
                self.skipTest("TCP 3002 is already in use")

        asr = FakeASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge, port=3002) as url:
            self.assertEqual(url, "ws://127.0.0.1:3002/v1/voice")
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("port-3002"))
                ready = await receive_json(websocket)
                self.assertEqual(ready["payload"]["partialIntervalMs"], 0)
                for sequence in range(3):
                    await websocket.send(audio_frame(sequence, sample=1_000))
                await websocket.send(envelope("session.stop", "port-3002"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )
        self.assertEqual(asr.sample_counts, [4_800])

    async def test_default_mode_is_final_only_and_calls_asr_once(self) -> None:
        asr = FakeASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("final-only"))
                ready = await receive_json(websocket)
                self.assertEqual(ready["type"], "session.ready")
                self.assertEqual(ready["payload"]["partialIntervalMs"], 0)

                for sequence in range(10):
                    await websocket.send(audio_frame(sequence, sample=1_000))

                await asyncio.sleep(0.05)
                self.assertEqual(asr.sample_counts, [])

                await websocket.send(envelope("session.stop", "final-only"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )
        self.assertEqual(asr.sample_counts, [16_000])

    async def test_silence_bypasses_asr_and_llm(self) -> None:
        asr = FakeASR()
        claude_created = False

        def create_claude() -> FakeClaude:
            nonlocal claude_created
            claude_created = True
            return FakeClaude()

        bridge = VoiceBridge(asr, create_claude)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("silence"))
                await receive_json(websocket)
                for sequence in range(5):
                    await websocket.send(audio_frame(sequence, sample=0))
                await websocket.send(envelope("session.stop", "silence"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )
        self.assertEqual(messages[1]["payload"]["text"], "")
        self.assertEqual(asr.sample_counts, [])
        self.assertFalse(claude_created)

    async def test_low_level_noise_bypasses_asr_and_llm(self) -> None:
        asr = FakeASR()
        claude_created = False

        def create_claude() -> FakeClaude:
            nonlocal claude_created
            claude_created = True
            return FakeClaude()

        bridge = VoiceBridge(asr, create_claude)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("low-noise"))
                await receive_json(websocket)
                for sequence in range(5):
                    await websocket.send(audio_frame(sequence, sample=20))
                await websocket.send(envelope("session.stop", "low-noise"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )
        self.assertEqual(messages[1]["payload"]["text"], "")
        self.assertEqual(asr.sample_counts, [])
        self.assertFalse(claude_created)

    async def test_trims_only_leading_and_trailing_silence(self) -> None:
        asr = FakeASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("trim-silence"))
                await receive_json(websocket)

                samples = ([0] * 10) + ([2_000] * 2) + ([0] * 2)
                samples += [2_000] * 2
                samples += [0] * 10
                for sequence, sample in enumerate(samples):
                    await websocket.send(audio_frame(sequence, sample=sample))

                await websocket.send(envelope("session.stop", "trim-silence"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "transcript.final", "session.completed"],
        )
        self.assertEqual(asr.sample_counts, [14_400])

    async def test_timing_logs_cover_asr_llm_and_session(self) -> None:
        bridge = VoiceBridge(FakeASR(), lambda: FakeClaude())

        with self.assertLogs("thirdhand.voice_bridge", level="INFO") as captured:
            async with running_bridge(bridge) as url:
                async with connect(
                    url,
                    subprotocols=[WEBSOCKET_SUBPROTOCOL],
                ) as websocket:
                    await websocket.send(start_message("timings"))
                    await receive_json(websocket)
                    await websocket.send(audio_frame(0, sample=1_000))
                    await websocket.send(envelope("session.stop", "timings"))
                    await receive_through(websocket, "session.completed")

        asr_log = next(
            (line for line in captured.output if "asr_timing" in line),
            "",
        )
        llm_log = next(
            (line for line in captured.output if "llm_timing" in line),
            "",
        )
        session_log = next(
            (line for line in captured.output if "session_timing" in line),
            "",
        )

        self.assertTrue(asr_log, captured.output)
        self.assertTrue(llm_log, captured.output)
        self.assertTrue(session_log, captured.output)
        for key in (
            "input_ms",
            "trimmed_ms",
            "queue_ms",
            "inference_ms",
            "total_ms",
        ):
            self.assertRegex(asr_log, rf"\b{key}=\d+(?:\.\d+)?")
        self.assertIn("silence=false", asr_log)

        for key in ("queue_ms", "factory_ms", "chat_ms", "total_ms"):
            self.assertRegex(llm_log, rf"\b{key}=\d+(?:\.\d+)?")

        for key in (
            "recording_ms",
            "stop_to_final_ms",
            "stop_to_completed_ms",
            "total_ms",
        ):
            self.assertRegex(session_log, rf"\b{key}=\d+(?:\.\d+)?")
        self.assertIn("status=completed", session_log)

    async def test_full_round_trip_and_event_order(self) -> None:
        asr = FakeASR()
        claude = FakeClaude()
        bridge = VoiceBridge(
            asr,
            lambda: claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                session_id = "round-trip"
                await websocket.send(envelope("ping", None))
                pong = await receive_json(websocket)
                self.assertEqual(pong["type"], "pong")

                await websocket.send(start_message(session_id))
                ready = await receive_json(websocket)
                self.assertEqual(ready["type"], "session.ready")
                self.assertEqual(ready["sessionId"], session_id)

                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", session_id))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            [
                "session.processing",
                "transcript.final",
                "assistant.response",
                "intent.candidate",
                "session.completed",
            ],
        )
        final = messages[1]["payload"]
        self.assertEqual(final["text"], "识别到 1600 个采样")
        self.assertEqual(final["language"], "zh")
        self.assertEqual(messages[2]["payload"]["text"], "好的，我已理解你的指令。")
        candidate = messages[3]["payload"]
        self.assertEqual(candidate["tool"], "release")
        self.assertEqual(candidate["intent"], "gripper.open")
        self.assertTrue(candidate["requiresConfirmation"])
        self.assertEqual(claude.inputs, ["识别到 1600 个采样"])
        self.assertEqual(asr.sample_counts, [1600])

    async def test_llm_failure_keeps_final_transcript(self) -> None:
        bridge = VoiceBridge(
            FakeASR(),
            lambda: FakeClaude(failure=RuntimeError("CC-Switch offline")),
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("llm-failure"))
                self.assertEqual((await receive_json(websocket))["type"], "session.ready")
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "llm-failure"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            [
                "session.processing",
                "transcript.final",
                "error",
                "session.completed",
            ],
        )
        self.assertEqual(messages[2]["payload"]["code"], "LLM_UNAVAILABLE")
        self.assertTrue(messages[3]["payload"]["asrSucceeded"])
        self.assertFalse(messages[3]["payload"]["llmAvailable"])

    async def test_asr_failure_is_reported_without_calling_llm(self) -> None:
        claude_created = False

        def create_claude() -> FakeClaude:
            nonlocal claude_created
            claude_created = True
            return FakeClaude()

        bridge = VoiceBridge(
            FakeASR(failure=RuntimeError("ASR unavailable")),
            create_claude,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("asr-failure"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "asr-failure"))
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["session.processing", "error", "session.completed"],
        )
        self.assertEqual(messages[1]["payload"]["code"], "ASR_FAILED")
        self.assertFalse(messages[2]["payload"]["asrSucceeded"])
        self.assertFalse(claude_created)

    async def test_bad_frames_duplicate_start_and_cancel(self) -> None:
        bridge = VoiceBridge(FakeASR(), None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(audio_frame(0))
                before_start = await receive_json(websocket)
                self.assertEqual(before_start["payload"]["code"], "INVALID_STATE")

                await websocket.send(start_message("bad-frame"))
                self.assertEqual((await receive_json(websocket))["type"], "session.ready")

                await websocket.send(start_message("second-session"))
                duplicate = await receive_json(websocket)
                self.assertEqual(duplicate["payload"]["code"], "INVALID_STATE")

                await websocket.send(audio_frame(0, magic=b"NOPE"))
                bad_magic = await receive_json(websocket)
                self.assertEqual(bad_magic["payload"]["code"], "BAD_AUDIO_FRAME")

                await websocket.send(audio_frame(1))
                bad_sequence = await receive_json(websocket)
                self.assertEqual(
                    bad_sequence["payload"]["code"],
                    "AUDIO_SEQUENCE_GAP",
                )

                await websocket.send(audio_frame(0, elapsed_ms=1))
                bad_elapsed = await receive_json(websocket)
                self.assertEqual(bad_elapsed["payload"]["code"], "BAD_AUDIO_FRAME")

                await websocket.send(
                    envelope(
                        "session.cancel",
                        "bad-frame",
                        {"reason": "test_complete"},
                    )
                )
                cancelled = await receive_json(websocket)
                self.assertEqual(cancelled["type"], "session.cancelled")

                await websocket.send(start_message("after-cancel"))
                restarted = await receive_json(websocket)
                self.assertEqual(restarted["type"], "session.ready")

    async def test_recording_limit_clears_session(self) -> None:
        bridge = VoiceBridge(
            FakeASR(),
            None,
            max_recording_seconds=0.1,
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("too-long"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0))
                await websocket.send(audio_frame(1))
                error = await receive_json(websocket)
                self.assertEqual(error["payload"]["code"], "RECORDING_LIMIT")

                await websocket.send(start_message("fresh"))
                ready = await receive_json(websocket)
                self.assertEqual(ready["type"], "session.ready")

    async def test_concurrent_clients_keep_audio_separate(self) -> None:
        asr = FakeASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as client_a:
                async with connect(
                    url,
                    subprotocols=[WEBSOCKET_SUBPROTOCOL],
                ) as client_b:
                    await client_a.send(start_message("client-a"))
                    await client_b.send(start_message("client-b"))
                    await asyncio.gather(
                        receive_json(client_a),
                        receive_json(client_b),
                    )

                    await client_a.send(audio_frame(0, sample=1_000))
                    await client_b.send(audio_frame(0, sample=1_000))
                    await client_b.send(audio_frame(1, sample=1_000))
                    await client_a.send(envelope("session.stop", "client-a"))
                    await client_b.send(envelope("session.stop", "client-b"))

                    result_a, result_b = await asyncio.gather(
                        receive_through(client_a, "session.completed"),
                        receive_through(client_b, "session.completed"),
                    )

        final_a = next(
            message for message in result_a if message["type"] == "transcript.final"
        )
        final_b = next(
            message for message in result_b if message["type"] == "transcript.final"
        )
        self.assertEqual(final_a["payload"]["text"], "识别到 1600 个采样")
        self.assertEqual(final_b["payload"]["text"], "识别到 3200 个采样")
        self.assertCountEqual(asr.sample_counts, [1600, 3200])

    async def test_cancel_during_llm_suppresses_late_results(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        bridge = VoiceBridge(
            FakeASR(),
            lambda: FakeClaude(entered=entered, release=release),
        )

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("cancel-llm"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "cancel-llm"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "transcript.final",
                )
                self.assertTrue(
                    await asyncio.to_thread(entered.wait, 1),
                    "Claude test double was not called",
                )

                await websocket.send(
                    envelope("session.cancel", "cancel-llm", {"reason": "user"})
                )
                cancelled = await receive_json(websocket)
                self.assertEqual(cancelled["type"], "session.cancelled")
                release.set()

                with self.assertRaises(asyncio.TimeoutError):
                    await receive_json(websocket, timeout=0.15)

    async def test_cancelled_asr_does_not_overlap_next_inference(self) -> None:
        asr = BlockingFirstASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("cancel-asr"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "cancel-asr"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                self.assertTrue(
                    await asyncio.to_thread(asr.entered.wait, 1),
                    "ASR test double was not called",
                )

                await websocket.send(envelope("session.cancel", "cancel-asr"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.cancelled",
                )

                await websocket.send(start_message("next-asr"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "next-asr"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                with self.assertRaises(asyncio.TimeoutError):
                    await receive_json(websocket, timeout=0.1)

                asr.release.set()
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["transcript.final", "session.completed"],
        )
        self.assertEqual(asr.call_count, 2)
        self.assertEqual(asr.max_active, 1)

    async def test_consecutive_recordings_on_one_connection_do_not_mix(self) -> None:
        asr = FakeASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("recording-one"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "recording-one"))
                first = await receive_through(websocket, "session.completed")

                await websocket.send(start_message("recording-two"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(audio_frame(1, sample=1_000))
                await websocket.send(envelope("session.stop", "recording-two"))
                second = await receive_through(websocket, "session.completed")

        first_final = next(
            message for message in first if message["type"] == "transcript.final"
        )
        second_final = next(
            message for message in second if message["type"] == "transcript.final"
        )
        self.assertEqual(first_final["sessionId"], "recording-one")
        self.assertEqual(second_final["sessionId"], "recording-two")
        self.assertEqual(first_final["payload"]["text"], "识别到 1600 个采样")
        self.assertEqual(second_final["payload"]["text"], "识别到 3200 个采样")
        self.assertEqual(asr.sample_counts, [1_600, 3_200])

    async def test_ping_remains_responsive_while_final_asr_is_slow(self) -> None:
        asr = BlockingFirstASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as websocket:
                await websocket.send(start_message("slow-asr-ping"))
                await receive_json(websocket)
                await websocket.send(audio_frame(0, sample=1_000))
                await websocket.send(envelope("session.stop", "slow-asr-ping"))
                self.assertEqual(
                    (await receive_json(websocket))["type"],
                    "session.processing",
                )
                self.assertTrue(
                    await asyncio.to_thread(asr.entered.wait, 1),
                    "ASR test double was not called",
                )

                ping = envelope("ping", "slow-asr-ping")
                ping_message_id = json.loads(ping)["messageId"]
                await websocket.send(ping)
                pong = await receive_json(websocket, timeout=0.25)
                self.assertEqual(pong["type"], "pong")
                self.assertEqual(pong["replyTo"], ping_message_id)

                asr.release.set()
                messages = await receive_through(websocket, "session.completed")

        self.assertEqual(
            [message["type"] for message in messages],
            ["transcript.final", "session.completed"],
        )
        self.assertEqual(asr.call_count, 1)
        self.assertEqual(asr.max_active, 1)

    async def test_disconnect_then_reconnect_does_not_overlap_asr(self) -> None:
        asr = BlockingFirstASR()
        bridge = VoiceBridge(asr, None)

        async with running_bridge(bridge) as url:
            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as client_a:
                await client_a.send(start_message("disconnect-a"))
                await receive_json(client_a)
                await client_a.send(audio_frame(0, sample=1_000))
                await client_a.send(envelope("session.stop", "disconnect-a"))
                self.assertEqual(
                    (await receive_json(client_a))["type"],
                    "session.processing",
                )
                self.assertTrue(
                    await asyncio.to_thread(asr.entered.wait, 1),
                    "ASR test double was not called",
                )

            async with connect(
                url,
                subprotocols=[WEBSOCKET_SUBPROTOCOL],
            ) as client_b:
                await client_b.send(start_message("reconnect-b"))
                await receive_json(client_b)
                await client_b.send(audio_frame(0, sample=1_000))
                await client_b.send(envelope("session.stop", "reconnect-b"))
                self.assertEqual(
                    (await receive_json(client_b))["type"],
                    "session.processing",
                )

                with self.assertRaises(asyncio.TimeoutError):
                    await receive_json(client_b, timeout=0.1)

                asr.release.set()
                messages = await receive_through(client_b, "session.completed")

        final = next(
            message for message in messages if message["type"] == "transcript.final"
        )
        self.assertEqual(final["sessionId"], "reconnect-b")
        self.assertEqual(asr.call_count, 2)
        self.assertEqual(asr.max_active, 1)


class VoiceBridgeSafetyTests(unittest.TestCase):
    def test_bridge_imports_only_existing_asr_and_claude_classes(self) -> None:
        source_path = Path(__file__).with_name("voice_bridge.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "voice_agent":
                imported_names.extend(alias.name for alias in node.names)

        self.assertEqual(imported_names, ["ClaudeAgent", "WhisperASR"])
        self.assertNotIn("RobotExecutor", source)
        self.assertNotIn("localhost:3000", source)
        self.assertNotIn("VoiceAgent.run", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
