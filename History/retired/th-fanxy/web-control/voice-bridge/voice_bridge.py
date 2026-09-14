#!/usr/bin/env python3
"""
ThirdHand Voice Bridge.

Receives browser microphone audio over Voice Protocol v1, delegates speech
recognition and language understanding to the existing Jetson voice_agent.py,
and returns text results to the browser.

This bridge deliberately does not import or invoke the robot executor, local
audio capture, or TTS playback.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

try:
    from websockets.asyncio.server import serve
except ImportError:  # websockets <= 13
    from websockets import serve

try:
    from websockets.exceptions import ConnectionClosed
except ImportError:  # pragma: no cover - compatibility fallback
    ConnectionClosed = Exception


PROTOCOL_VERSION = 1
WEBSOCKET_SUBPROTOCOL = "thirdhand.voice.v1"
WEBSOCKET_PATH = "/v1/voice"

AUDIO_MAGIC = b"THV1"
AUDIO_HEADER_BYTES = 12
AUDIO_SAMPLE_RATE = 16_000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_BYTES = 2
AUDIO_FRAME_MS = 100
AUDIO_FRAME_PCM_BYTES = (
    AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_BYTES * AUDIO_FRAME_MS // 1000
)
AUDIO_FRAME_BYTES = AUDIO_HEADER_BYTES + AUDIO_FRAME_PCM_BYTES

DEFAULT_MAX_RECORDING_SECONDS = 30.0
DEFAULT_PARTIAL_INTERVAL_SECONDS = 0.0
DEFAULT_LLM_TIMEOUT_SECONDS = 45.0
DEFAULT_SILENCE_RMS_THRESHOLD = 0.003
DEFAULT_MIN_VOICED_MS = 60
DEFAULT_TRIM_PADDING_MS = 150
AUDIO_ANALYSIS_FRAME_MS = 20
MAX_TEXT_INPUT_CHARS = 2_000
MAX_WEBSOCKET_MESSAGE_BYTES = 16_384

LOG = logging.getLogger("thirdhand.voice_bridge")


class ProtocolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        session_id: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.session_id = session_id
        self.reply_to = reply_to


@dataclass
class RecordingSession:
    session_id: str
    started_at: float
    max_pcm_bytes: int
    pcm: bytearray = field(default_factory=bytearray)
    expected_sequence: int = 0
    generation: int = 0
    active: bool = True
    stopping: bool = False
    cancelled: bool = False
    stop_received_at: Optional[float] = None
    final_task: Optional[asyncio.Task] = None


@dataclass(frozen=True)
class PreparedAudio:
    audio: Any
    input_samples: int
    output_samples: int
    is_silence: bool


@dataclass
class ConnectionContext:
    websocket: Any
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    claude_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    session: Optional[RecordingSession] = None
    text_session_id: Optional[str] = None
    text_task: Optional[asyncio.Task] = None
    claude: Any = None
    claude_generation: int = 0
    closed: bool = False


def now_ms() -> int:
    return int(time.time() * 1000)


def make_envelope(
    message_type: str,
    session_id: Optional[str],
    payload: Optional[dict[str, Any]] = None,
    *,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "type": message_type,
        "messageId": str(uuid.uuid4()),
        "replyTo": reply_to,
        "sessionId": session_id,
        "ts": now_ms(),
        "payload": payload or {},
    }


def connection_path(websocket: Any, legacy_path: Optional[str]) -> Optional[str]:
    if legacy_path:
        return legacy_path.split("?", 1)[0]
    request = getattr(websocket, "request", None)
    request_path = getattr(request, "path", None)
    if request_path:
        return request_path.split("?", 1)[0]
    path = getattr(websocket, "path", None)
    return path.split("?", 1)[0] if path else None


def validate_control_message(raw: str) -> dict[str, Any]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProtocolError("BAD_MESSAGE", "Control messages must be valid JSON.") from error

    if not isinstance(message, dict):
        raise ProtocolError("BAD_MESSAGE", "Control messages must be JSON objects.")

    session_id = message.get("sessionId")
    reply_to = message.get("messageId")

    if message.get("v") != PROTOCOL_VERSION:
        raise ProtocolError(
            "UNSUPPORTED_VERSION",
            "Only Voice Protocol v1 is supported.",
            recoverable=False,
            session_id=session_id,
            reply_to=reply_to,
        )
    if not isinstance(message.get("type"), str) or not message["type"]:
        raise ProtocolError(
            "BAD_MESSAGE",
            "Message type is required.",
            session_id=session_id,
            reply_to=reply_to,
        )
    if not isinstance(reply_to, str) or not reply_to:
        raise ProtocolError(
            "BAD_MESSAGE",
            "messageId is required.",
            session_id=session_id,
        )
    if not isinstance(message.get("payload"), dict):
        raise ProtocolError(
            "BAD_MESSAGE",
            "payload must be an object.",
            session_id=session_id,
            reply_to=reply_to,
        )
    return message


class VoiceBridge:
    def __init__(
        self,
        asr: Any,
        claude_factory: Optional[Callable[[], Any]],
        *,
        partial_interval_seconds: float = DEFAULT_PARTIAL_INTERVAL_SECONDS,
        max_recording_seconds: float = DEFAULT_MAX_RECORDING_SECONDS,
        llm_timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS,
        silence_rms_threshold: float = DEFAULT_SILENCE_RMS_THRESHOLD,
        min_voiced_ms: int = DEFAULT_MIN_VOICED_MS,
        trim_padding_ms: int = DEFAULT_TRIM_PADDING_MS,
    ) -> None:
        if partial_interval_seconds != 0:
            raise ValueError(
                "partial transcription is disabled in final-only mode; "
                "partial_interval_seconds must be 0"
            )
        if max_recording_seconds <= 0:
            raise ValueError("max_recording_seconds must be positive")
        if not 0 < silence_rms_threshold < 1:
            raise ValueError("silence_rms_threshold must be between 0 and 1")
        if min_voiced_ms <= 0:
            raise ValueError("min_voiced_ms must be positive")
        if trim_padding_ms < 0:
            raise ValueError("trim_padding_ms cannot be negative")

        self.asr = asr
        self.claude_factory = claude_factory
        self.partial_interval_seconds = 0.0
        self.max_recording_seconds = max_recording_seconds
        self.llm_timeout_seconds = llm_timeout_seconds
        self.silence_rms_threshold = silence_rms_threshold
        self.min_voiced_ms = min_voiced_ms
        self.trim_padding_ms = trim_padding_ms
        self.asr_lock = asyncio.Lock()
        self.background_tasks: set[asyncio.Task] = set()

    async def handle_connection(
        self,
        websocket: Any,
        legacy_path: Optional[str] = None,
    ) -> None:
        path = connection_path(websocket, legacy_path)
        if path != WEBSOCKET_PATH:
            await websocket.close(code=1008, reason="Unsupported WebSocket path")
            return
        if getattr(websocket, "subprotocol", None) != WEBSOCKET_SUBPROTOCOL:
            await websocket.close(code=1002, reason="Voice subprotocol is required")
            return

        context = ConnectionContext(websocket=websocket)
        peer = getattr(websocket, "remote_address", None)
        LOG.info("client connected peer=%s", peer)

        try:
            async for incoming in websocket:
                if isinstance(incoming, bytes):
                    await self._handle_audio(context, incoming)
                elif isinstance(incoming, str):
                    await self._handle_control(context, incoming)
                else:
                    await self._send_error(
                        context,
                        "BAD_MESSAGE",
                        "Unsupported WebSocket message type.",
                    )
        except ConnectionClosed:
            pass
        finally:
            context.closed = True
            self._discard_session(context)
            LOG.info("client disconnected peer=%s", peer)

    async def _handle_control(self, context: ConnectionContext, raw: str) -> None:
        try:
            message = validate_control_message(raw)
            message_type = message["type"]

            if message_type == "ping":
                await self._send(
                    context,
                    "pong",
                    message.get("sessionId"),
                    {},
                    reply_to=message["messageId"],
                )
            elif message_type == "session.start":
                await self._start_session(context, message)
            elif message_type == "session.stop":
                await self._stop_session(context, message)
            elif message_type == "session.cancel":
                await self._cancel_session(context, message)
            elif message_type == "text.submit":
                await self._submit_text(context, message)
            else:
                raise ProtocolError(
                    "UNKNOWN_MESSAGE",
                    f"Unknown message type: {message_type}",
                    session_id=message.get("sessionId"),
                    reply_to=message.get("messageId"),
                )
        except ProtocolError as error:
            await self._send_error(
                context,
                error.code,
                error.message,
                recoverable=error.recoverable,
                session_id=error.session_id,
                reply_to=error.reply_to,
            )
        except Exception:
            LOG.exception("unexpected control-message failure")
            await self._send_error(
                context,
                "INTERNAL",
                "Voice Bridge could not process the control message.",
                recoverable=False,
            )

    async def _start_session(
        self,
        context: ConnectionContext,
        message: dict[str, Any],
    ) -> None:
        if context.session is not None or context.text_session_id is not None:
            raise ProtocolError(
                "INVALID_STATE",
                "Another audio or text session is already active or processing.",
                session_id=message.get("sessionId"),
                reply_to=message["messageId"],
            )

        session_id = message.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise ProtocolError(
                "BAD_MESSAGE",
                "sessionId is required for session.start.",
                reply_to=message["messageId"],
            )

        audio = message["payload"].get("audio")
        expected_audio = {
            "encoding": "pcm_s16le",
            "sampleRate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
            "frameMs": AUDIO_FRAME_MS,
        }
        if not isinstance(audio, dict) or any(
            audio.get(key) != value for key, value in expected_audio.items()
        ):
            raise ProtocolError(
                "UNSUPPORTED_AUDIO",
                "Use PCM S16LE, 16 kHz, mono, 100 ms frames.",
                recoverable=False,
                session_id=session_id,
                reply_to=message["messageId"],
            )

        bytes_per_second = AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_BYTES
        context.session = RecordingSession(
            session_id=session_id,
            started_at=time.monotonic(),
            max_pcm_bytes=int(bytes_per_second * self.max_recording_seconds),
        )
        await self._send(
            context,
            "session.ready",
            session_id,
            {
                "audio": expected_audio,
                "partialIntervalMs": int(self.partial_interval_seconds * 1000),
                "maxRecordingMs": int(self.max_recording_seconds * 1000),
            },
            reply_to=message["messageId"],
        )

    async def _stop_session(
        self,
        context: ConnectionContext,
        message: dict[str, Any],
    ) -> None:
        session = self._matching_session(context, message)
        if not session.active:
            raise ProtocolError(
                "INVALID_STATE",
                "The recording session is no longer accepting audio.",
                session_id=message.get("sessionId"),
                reply_to=message["messageId"],
            )

        session.active = False
        session.stopping = True
        session.stop_received_at = time.monotonic()
        await self._send(
            context,
            "session.processing",
            session.session_id,
            {
                "inputMode": "audio",
                "receivedAudioBytes": len(session.pcm),
            },
            reply_to=message["messageId"],
        )
        session.final_task = self._track(
            asyncio.create_task(self._finalize_session(context, session))
        )

    async def _cancel_session(
        self,
        context: ConnectionContext,
        message: dict[str, Any],
    ) -> None:
        requested_id = message.get("sessionId")
        reason = message["payload"].get("reason", "client_cancelled")
        session = context.session

        if session is not None and requested_id == session.session_id:
            session.cancelled = True
            session.active = False
            session.generation += 1
            self._cancel_session_tasks(session)
            session.pcm.clear()
            context.session = None
            if session.stopping:
                # A final task may already be inside ClaudeAgent.chat(). Retire
                # that instance after cancellation; cancelling a recording
                # before LLM work starts must preserve the conversation history.
                self._retire_claude(context)
            await self._send(
                context,
                "session.cancelled",
                session.session_id,
                {"inputMode": "audio", "reason": reason},
                reply_to=message["messageId"],
            )
            return

        if (
            isinstance(requested_id, str)
            and requested_id
            and requested_id == context.text_session_id
        ):
            task = context.text_task
            context.text_session_id = None
            context.text_task = None
            self._retire_claude(context)
            if task is not None and not task.done():
                task.cancel()
            await self._send(
                context,
                "session.cancelled",
                requested_id,
                {"inputMode": "text", "reason": reason},
                reply_to=message["messageId"],
            )
            return

        raise ProtocolError(
            "INVALID_STATE",
            "No matching audio or text session is active.",
            session_id=requested_id,
            reply_to=message["messageId"],
        )

    async def _submit_text(
        self,
        context: ConnectionContext,
        message: dict[str, Any],
    ) -> None:
        session_id = message.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            raise ProtocolError(
                "BAD_MESSAGE",
                "sessionId is required for text.submit.",
                reply_to=message["messageId"],
            )
        if context.session is not None or context.text_session_id is not None:
            raise ProtocolError(
                "INVALID_STATE",
                "Another audio or text session is already active or processing.",
                session_id=session_id,
                reply_to=message["messageId"],
            )

        raw_text = message["payload"].get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise ProtocolError(
                "BAD_MESSAGE",
                "payload.text must be a non-empty string.",
                session_id=session_id,
                reply_to=message["messageId"],
            )
        text = raw_text.strip()
        if len(text) > MAX_TEXT_INPUT_CHARS:
            raise ProtocolError(
                "TEXT_TOO_LONG",
                f"Text input cannot exceed {MAX_TEXT_INPUT_CHARS} characters.",
                session_id=session_id,
                reply_to=message["messageId"],
            )

        context.text_session_id = session_id
        await self._send(
            context,
            "session.processing",
            session_id,
            {
                "inputMode": "text",
                "textLength": len(text),
            },
            reply_to=message["messageId"],
        )
        context.text_task = self._track(
            asyncio.create_task(
                self._process_text(
                    context,
                    session_id,
                    text,
                    message["messageId"],
                )
            )
        )

    async def _process_text(
        self,
        context: ConnectionContext,
        session_id: str,
        text: str,
        reply_to: str,
    ) -> None:
        candidate_count = 0
        llm_available = False

        try:
            if context.closed or context.text_session_id != session_id:
                return

            try:
                if self.claude_factory is None:
                    raise RuntimeError("ClaudeAgent is disabled.")

                llm_result = await self._understand(
                    context,
                    text,
                    session_id=session_id,
                    input_mode="text",
                )
                if context.closed or context.text_session_id != session_id:
                    return

                llm_available = True
                reply_text = str(llm_result.get("text") or "").strip()
                if reply_text:
                    await self._send(
                        context,
                        "assistant.response",
                        session_id,
                        {"inputMode": "text", "text": reply_text},
                        reply_to=reply_to,
                    )

                for action in llm_result.get("actions") or []:
                    if context.closed or context.text_session_id != session_id:
                        return
                    candidate = self._candidate_from_action(action, text)
                    if candidate is None:
                        continue
                    candidate_count += 1
                    await self._send(
                        context,
                        "intent.candidate",
                        session_id,
                        candidate,
                        reply_to=reply_to,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if context.closed or context.text_session_id != session_id:
                    return
                LOG.warning(
                    "text understanding failed session=%s error=%s",
                    session_id,
                    error,
                )
                self._retire_claude(context)
                await self._send_error(
                    context,
                    "LLM_UNAVAILABLE",
                    str(error) or "Language understanding is unavailable.",
                    session_id=session_id,
                    reply_to=reply_to,
                )

            if context.closed or context.text_session_id != session_id:
                return
            await self._send(
                context,
                "session.completed",
                session_id,
                {
                    "inputMode": "text",
                    "llmAvailable": llm_available,
                    "candidateCount": candidate_count,
                },
                reply_to=reply_to,
            )
        finally:
            if context.text_session_id == session_id:
                context.text_session_id = None
            current_task = asyncio.current_task()
            if context.text_task is current_task:
                context.text_task = None

    def _matching_session(
        self,
        context: ConnectionContext,
        message: dict[str, Any],
    ) -> RecordingSession:
        session = context.session
        requested_id = message.get("sessionId")
        if session is None or requested_id != session.session_id:
            raise ProtocolError(
                "INVALID_STATE",
                "No matching recording session is active.",
                session_id=requested_id,
                reply_to=message["messageId"],
            )
        return session

    async def _handle_audio(
        self,
        context: ConnectionContext,
        frame: bytes,
    ) -> None:
        session = context.session
        if session is None or not session.active:
            await self._send_error(
                context,
                "INVALID_STATE",
                "Audio arrived before session.start or after session.stop.",
                session_id=session.session_id if session else None,
            )
            return

        if len(frame) != AUDIO_FRAME_BYTES or frame[:4] != AUDIO_MAGIC:
            await self._send_error(
                context,
                "BAD_AUDIO_FRAME",
                f"Expected {AUDIO_FRAME_BYTES} bytes with a THV1 header.",
                session_id=session.session_id,
            )
            return

        sequence, elapsed_ms = struct.unpack_from("<II", frame, 4)
        if sequence != session.expected_sequence:
            await self._send_error(
                context,
                "AUDIO_SEQUENCE_GAP",
                f"Expected audio sequence {session.expected_sequence}, received {sequence}.",
                session_id=session.session_id,
            )
            return
        if elapsed_ms != sequence * AUDIO_FRAME_MS:
            await self._send_error(
                context,
                "BAD_AUDIO_FRAME",
                (
                    f"Expected elapsedMs {sequence * AUDIO_FRAME_MS}, "
                    f"received {elapsed_ms}."
                ),
                session_id=session.session_id,
            )
            return

        pcm = frame[AUDIO_HEADER_BYTES:]
        if len(session.pcm) + len(pcm) > session.max_pcm_bytes:
            session.active = False
            session.cancelled = True
            session.generation += 1
            session.pcm.clear()
            context.session = None
            await self._send_error(
                context,
                "RECORDING_LIMIT",
                f"Recording exceeded {self.max_recording_seconds:.0f} seconds.",
                session_id=session.session_id,
            )
            return

        session.pcm.extend(pcm)
        session.expected_sequence += 1

    async def _finalize_session(
        self,
        context: ConnectionContext,
        session: RecordingSession,
    ) -> None:
        candidate_count = 0
        llm_available = False
        snapshot = bytes(session.pcm)
        stop_received_at = session.stop_received_at or time.monotonic()
        recording_ms = max(
            0.0,
            (stop_received_at - session.started_at) * 1000,
        )
        stop_to_final_ms = 0.0
        status = "processing"

        try:
            if session.cancelled or context.closed:
                return

            if snapshot:
                try:
                    result = await self._transcribe(
                        snapshot,
                        session_id=session.session_id,
                        phase="final",
                    )
                except Exception as error:
                    status = "asr_failed"
                    LOG.exception("final ASR failed session=%s", session.session_id)
                    await self._send_error(
                        context,
                        "ASR_FAILED",
                        str(error) or "Speech recognition failed.",
                        session_id=session.session_id,
                    )
                    if context.session is session:
                        context.session = None
                    await self._send(
                        context,
                        "session.completed",
                        session.session_id,
                        {
                            "inputMode": "audio",
                            "asrSucceeded": False,
                            "llmAvailable": False,
                            "candidateCount": 0,
                        },
                    )
                    return
            else:
                result = {
                    "text": "",
                    "language": None,
                    "duration": 0.0,
                    "language_prob": None,
                }

            if session.cancelled or context.closed:
                return

            final_text = str(result.get("text") or "").strip()
            final_payload: dict[str, Any] = {
                "segmentId": f"{session.session_id}:segment-1",
                "text": final_text,
            }
            for source_key, target_key in (
                ("language", "language"),
                ("duration", "duration"),
                ("language_prob", "languageConfidence"),
            ):
                value = result.get(source_key)
                if value is not None:
                    final_payload[target_key] = value
            await self._send(
                context,
                "transcript.final",
                session.session_id,
                final_payload,
            )
            stop_to_final_ms = max(
                0.0,
                (time.monotonic() - stop_received_at) * 1000,
            )

            if final_text and self.claude_factory is not None:
                try:
                    llm_result = await self._understand(
                        context,
                        final_text,
                        session_id=session.session_id,
                        input_mode="audio",
                    )
                    if (
                        context.closed
                        or context.session is not session
                        or session.cancelled
                    ):
                        return
                    llm_available = True
                    reply_text = str(llm_result.get("text") or "").strip()
                    actions = llm_result.get("actions") or []
                    if reply_text:
                        await self._send(
                            context,
                            "assistant.response",
                            session.session_id,
                            {"text": reply_text},
                        )
                    for action in actions:
                        candidate = self._candidate_from_action(action, final_text)
                        if candidate is None:
                            continue
                        candidate_count += 1
                        await self._send(
                            context,
                            "intent.candidate",
                            session.session_id,
                            candidate,
                        )
                except Exception as error:
                    LOG.warning(
                        "language understanding failed session=%s error=%s",
                        session.session_id,
                        error,
                    )
                    self._retire_claude(context)
                    await self._send_error(
                        context,
                        "LLM_UNAVAILABLE",
                        str(error) or "Language understanding is unavailable.",
                        session_id=session.session_id,
                    )

            if context.session is session:
                context.session = None
            await self._send(
                context,
                "session.completed",
                session.session_id,
                {
                    "inputMode": "audio",
                    "asrSucceeded": True,
                    "llmAvailable": llm_available,
                    "candidateCount": candidate_count,
                },
            )
            status = "completed"
        finally:
            if session.cancelled:
                status = "cancelled"
            elif context.closed:
                status = "disconnected"
            finished_at = time.monotonic()
            LOG.info(
                (
                    "session_timing session=%s input_mode=audio "
                    "recording_ms=%.1f stop_to_final_ms=%.1f "
                    "stop_to_completed_ms=%.1f total_ms=%.1f status=%s"
                ),
                session.session_id,
                recording_ms,
                stop_to_final_ms,
                max(0.0, (finished_at - stop_received_at) * 1000),
                max(0.0, (finished_at - session.started_at) * 1000),
                status,
            )
            session.pcm.clear()
            session.stopping = False
            if context.session is session:
                context.session = None

    def _prepare_audio(self, pcm: bytes) -> PreparedAudio:
        import numpy as np

        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        audio /= 32768.0
        input_samples = len(audio)
        if input_samples == 0:
            return PreparedAudio(audio, 0, 0, True)

        frame_samples = AUDIO_SAMPLE_RATE * AUDIO_ANALYSIS_FRAME_MS // 1000
        voiced_frames: list[bool] = []
        for start in range(0, input_samples, frame_samples):
            frame = audio[start : start + frame_samples]
            rms = float(np.sqrt(np.mean(frame * frame))) if len(frame) else 0.0
            voiced_frames.append(rms >= self.silence_rms_threshold)

        minimum_frames = max(
            1,
            (
                self.min_voiced_ms
                + AUDIO_ANALYSIS_FRAME_MS
                - 1
            )
            // AUDIO_ANALYSIS_FRAME_MS,
        )
        longest_run = 0
        current_run = 0
        for is_voiced in voiced_frames:
            if is_voiced:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 0

        if longest_run < minimum_frames:
            return PreparedAudio(audio[:0], input_samples, 0, True)

        first_voiced = voiced_frames.index(True)
        last_voiced = len(voiced_frames) - 1 - voiced_frames[::-1].index(True)
        padding_samples = AUDIO_SAMPLE_RATE * self.trim_padding_ms // 1000
        trim_start = max(0, first_voiced * frame_samples - padding_samples)
        trim_end = min(
            input_samples,
            (last_voiced + 1) * frame_samples + padding_samples,
        )
        trimmed = audio[trim_start:trim_end]
        return PreparedAudio(
            trimmed,
            input_samples,
            len(trimmed),
            False,
        )

    async def _transcribe(
        self,
        pcm: bytes,
        *,
        session_id: Optional[str] = None,
        phase: str = "final",
    ) -> dict[str, Any]:
        total_started_at = time.monotonic()
        input_ms = len(pcm) / (
            AUDIO_SAMPLE_RATE * AUDIO_CHANNELS * AUDIO_SAMPLE_BYTES
        ) * 1000
        trimmed_ms = 0.0
        queue_ms = 0.0
        inference_ms = 0.0
        is_silence = True
        status = "preparing"

        try:
            prepared = self._prepare_audio(pcm)
            trimmed_ms = prepared.output_samples / AUDIO_SAMPLE_RATE * 1000
            is_silence = prepared.is_silence
            if prepared.is_silence:
                status = "silence"
                return {
                    "text": "",
                    "language": None,
                    "duration": prepared.input_samples / AUDIO_SAMPLE_RATE,
                    "language_prob": None,
                }

            queued_at = time.monotonic()
            async with self.asr_lock:
                queue_ms = max(0.0, (time.monotonic() - queued_at) * 1000)
                inference_started_at = time.monotonic()
                # Cancelling an asyncio.to_thread() await does not stop its
                # native worker. Shield it and keep the model lock until that
                # worker has actually returned, so a cancelled session cannot
                # overlap a new inference on the same Whisper instance.
                worker = asyncio.create_task(
                    asyncio.to_thread(self.asr.transcribe, prepared.audio)
                )
                try:
                    result = await asyncio.shield(worker)
                except asyncio.CancelledError:
                    try:
                        await worker
                    except Exception:
                        LOG.debug(
                            "cancelled ASR worker finished with an error",
                            exc_info=True,
                        )
                    raise
                finally:
                    inference_ms = max(
                        0.0,
                        (time.monotonic() - inference_started_at) * 1000,
                    )
            if not isinstance(result, dict):
                raise RuntimeError(
                    "WhisperASR.transcribe() returned an invalid result"
                )
            status = "ok"
            return result
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except Exception:
            status = "error"
            raise
        finally:
            LOG.info(
                (
                    "asr_timing session=%s phase=%s input_ms=%.1f "
                    "trimmed_ms=%.1f queue_ms=%.1f inference_ms=%.1f "
                    "total_ms=%.1f silence=%s status=%s"
                ),
                session_id or "-",
                phase,
                input_ms,
                trimmed_ms,
                queue_ms,
                inference_ms,
                max(0.0, (time.monotonic() - total_started_at) * 1000),
                str(is_silence).lower(),
                status,
            )

    async def _understand(
        self,
        context: ConnectionContext,
        text: str,
        *,
        session_id: Optional[str] = None,
        input_mode: str = "unknown",
    ) -> dict[str, Any]:
        started = asyncio.Event()
        total_started_at = time.monotonic()
        queue_ms = 0.0
        factory_ms = 0.0
        chat_ms = 0.0
        status = "queued"

        async def invoke() -> Any:
            nonlocal queue_ms, factory_ms, chat_ms
            # asyncio cannot stop a function already running in a worker
            # thread. Serialize calls per connection so a cancelled or timed
            # out request can never overlap the next ClaudeAgent.chat().
            queued_at = time.monotonic()
            async with context.claude_lock:
                queue_ms = max(0.0, (time.monotonic() - queued_at) * 1000)
                started.set()
                generation = context.claude_generation
                if context.claude is None:
                    factory_started_at = time.monotonic()
                    try:
                        agent = await asyncio.to_thread(self.claude_factory)
                    finally:
                        factory_ms = max(
                            0.0,
                            (time.monotonic() - factory_started_at) * 1000,
                        )
                    if context.claude_generation != generation:
                        # Cancellation or timeout retired this generation while
                        # a slow factory was still running. Do not write the
                        # stale agent back or submit the cancelled prompt.
                        raise asyncio.CancelledError
                    context.claude = agent
                else:
                    agent = context.claude
                chat_started_at = time.monotonic()
                try:
                    return await asyncio.to_thread(agent.chat, text)
                finally:
                    chat_ms = max(
                        0.0,
                        (time.monotonic() - chat_started_at) * 1000,
                    )

        worker = self._track(asyncio.create_task(invoke()))
        try:
            result = await asyncio.wait_for(
                asyncio.shield(worker),
                timeout=self.llm_timeout_seconds,
            )
            status = "ok"
        except (asyncio.CancelledError, asyncio.TimeoutError) as error:
            status = (
                "timeout"
                if isinstance(error, asyncio.TimeoutError)
                else "cancelled"
            )
            # A queued call is safe to cancel. Once it has entered the lock,
            # leave it running so the lock remains held until the native
            # worker actually returns.
            if not started.is_set() and not worker.done():
                worker.cancel()
            raise
        except Exception:
            status = "error"
            raise
        finally:
            LOG.info(
                (
                    "llm_timing session=%s input_mode=%s queue_ms=%.1f "
                    "factory_ms=%.1f chat_ms=%.1f total_ms=%.1f status=%s"
                ),
                session_id or "-",
                input_mode,
                queue_ms,
                factory_ms,
                chat_ms,
                max(0.0, (time.monotonic() - total_started_at) * 1000),
                status,
            )
        if not isinstance(result, dict):
            raise RuntimeError("ClaudeAgent.chat() returned an invalid result")
        return result

    @staticmethod
    def _candidate_from_action(
        action: Any,
        source_text: str,
    ) -> Optional[dict[str, Any]]:
        if not isinstance(action, dict):
            return None
        tool = str(action.get("tool") or action.get("name") or "").strip()
        args = action.get("input", action.get("arguments"))
        if not isinstance(args, dict):
            args = {}

        if not tool or tool == "say":
            return None

        intent = tool
        mapped_args = dict(args)
        if tool == "emergency_stop":
            intent = "robot.estop"
        elif tool == "go_home":
            intent = "robot.preset"
            mapped_args = {"name": "home"}
        elif tool == "grasp":
            intent = "gripper.grip"
        elif tool == "release":
            intent = "gripper.open"
        elif tool == "move_to":
            intent = "robot.move_to"

        return {
            "candidateId": str(uuid.uuid4()),
            "intent": intent,
            "tool": tool,
            "args": mapped_args,
            "sourceText": source_text,
            "requiresConfirmation": True,
        }

    async def _send(
        self,
        context: ConnectionContext,
        message_type: str,
        session_id: Optional[str],
        payload: Optional[dict[str, Any]] = None,
        *,
        reply_to: Optional[str] = None,
    ) -> None:
        if context.closed:
            return
        envelope = make_envelope(
            message_type,
            session_id,
            payload,
            reply_to=reply_to,
        )
        try:
            async with context.send_lock:
                await context.websocket.send(
                    json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
                )
        except ConnectionClosed:
            context.closed = True

    async def _send_error(
        self,
        context: ConnectionContext,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        session_id: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> None:
        await self._send(
            context,
            "error",
            session_id,
            {
                "code": code,
                "message": message,
                "recoverable": recoverable,
            },
            reply_to=reply_to,
        )

    def _discard_session(self, context: ConnectionContext) -> None:
        text_task = context.text_task
        context.text_session_id = None
        context.text_task = None
        if text_task is not None and not text_task.done():
            self._retire_claude(context)
            text_task.cancel()

        session = context.session
        if session is None:
            return
        session.cancelled = True
        session.active = False
        session.generation += 1
        if session.stopping:
            self._retire_claude(context)
        self._cancel_session_tasks(session)
        session.pcm.clear()
        context.session = None

    @staticmethod
    def _cancel_session_tasks(session: RecordingSession) -> None:
        current = asyncio.current_task()
        for task in (session.final_task,):
            if task is not None and task is not current and not task.done():
                task.cancel()

    @staticmethod
    def _retire_claude(context: ConnectionContext) -> None:
        context.claude = None
        context.claude_generation += 1

    def _track(self, task: asyncio.Task) -> asyncio.Task:
        self.background_tasks.add(task)

        def forget(completed: asyncio.Task) -> None:
            self.background_tasks.discard(completed)
            if not completed.cancelled():
                # Retrieve background exceptions even when the original waiter
                # timed out or was cancelled, avoiding noisy orphan warnings.
                completed.exception()

        task.add_done_callback(forget)
        return task


async def run_server(args: argparse.Namespace) -> None:
    from voice_agent import ClaudeAgent, WhisperASR

    asr_options: dict[str, Any] = {}
    if args.whisper_model is not None:
        asr_options["model_size"] = args.whisper_model
    if args.language is not None:
        asr_options["language"] = args.language
    asr = WhisperASR(**asr_options)
    LOG.info(
        "loading Whisper model=%s",
        args.whisper_model or "voice_agent.py default",
    )
    await asyncio.to_thread(asr.load)

    claude_factory: Optional[Callable[[], Any]]
    if args.no_llm:
        claude_factory = None
    else:
        # Keep voice_agent.py's own model and CC-Switch configuration as the
        # source of truth instead of duplicating it in this bridge.
        claude_factory = ClaudeAgent

    bridge = VoiceBridge(
        asr,
        claude_factory,
        partial_interval_seconds=args.partial_interval,
        max_recording_seconds=args.max_recording_seconds,
        llm_timeout_seconds=args.llm_timeout,
        silence_rms_threshold=args.silence_rms_threshold,
        min_voiced_ms=args.min_voiced_ms,
        trim_padding_ms=args.trim_padding_ms,
    )

    LOG.info(
        "listening ws://%s:%d%s subprotocol=%s",
        args.host,
        args.port,
        WEBSOCKET_PATH,
        WEBSOCKET_SUBPROTOCOL,
    )
    async with serve(
        bridge.handle_connection,
        args.host,
        args.port,
        subprotocols=[WEBSOCKET_SUBPROTOCOL],
        max_size=MAX_WEBSOCKET_MESSAGE_BYTES,
        compression=None,
        ping_interval=None,
    ):
        await asyncio.Future()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bridge browser audio to the existing Jetson voice agent."
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3001)
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="Override voice_agent.py's default Whisper model.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Override voice_agent.py's default ASR language code.",
    )
    parser.add_argument(
        "--partial-interval",
        type=float,
        default=DEFAULT_PARTIAL_INTERVAL_SECONDS,
        help="Reserved for future streaming ASR; final-only mode requires 0.",
    )
    parser.add_argument(
        "--max-recording-seconds",
        type=float,
        default=DEFAULT_MAX_RECORDING_SECONDS,
    )
    parser.add_argument(
        "--silence-rms-threshold",
        type=float,
        default=DEFAULT_SILENCE_RMS_THRESHOLD,
        help=(
            "RMS gate in normalized PCM units; increase to reject more "
            "background noise."
        ),
    )
    parser.add_argument(
        "--min-voiced-ms",
        type=int,
        default=DEFAULT_MIN_VOICED_MS,
        help="Minimum consecutive above-threshold audio required for ASR.",
    )
    parser.add_argument(
        "--trim-padding-ms",
        type=int,
        default=DEFAULT_TRIM_PADDING_MS,
        help="Audio retained before and after detected speech.",
    )
    parser.add_argument(
        "--llm-timeout",
        type=float,
        default=DEFAULT_LLM_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Return ASR results without calling ClaudeAgent.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        LOG.info("voice bridge stopped")


if __name__ == "__main__":
    main()
