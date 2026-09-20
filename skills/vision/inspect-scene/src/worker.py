"""Read-only scene inspection primitives for the ThirdHand controller."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from email.parser import BytesHeaderParser
from pathlib import Path
import time
from typing import Callable, NamedTuple
from urllib.request import urlopen


MAX_JPEG_BYTES = 16 * 1024 * 1024
MAX_HEADER_BYTES = 16 * 1024


class FrameCaptureError(RuntimeError):
    """Safe frame-acquisition failure without leaking transport details."""

    def __init__(self, code: str, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class InspectSceneError(RuntimeError):
    """User-safe Skill failure."""

    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class CapturedFrame(NamedTuple):
    jpeg: bytes
    sequence: int
    captured_at_ms: int
    received_at_ms: int
    frame_age_ms: int
    timestamp_source: str


def _read_headers(response) -> dict[str, str]:
    boundary = response.readline(MAX_HEADER_BYTES + 1)
    if not boundary or len(boundary) > MAX_HEADER_BYTES or not boundary.startswith(b"--"):
        raise FrameCaptureError("invalid_stream", "视觉流没有返回有效的 MJPEG 边界。")

    raw = bytearray()
    while True:
        line = response.readline(MAX_HEADER_BYTES + 1)
        if not line:
            raise FrameCaptureError("invalid_stream", "视觉流在帧头完成前中断。")
        if line in {b"\r\n", b"\n"}:
            break
        raw.extend(line)
        if len(raw) > MAX_HEADER_BYTES:
            raise FrameCaptureError("invalid_stream", "视觉流帧头过大。", retryable=False)
    parsed = BytesHeaderParser().parsebytes(bytes(raw))
    return {key.lower(): value.strip() for key, value in parsed.items()}


def read_mjpeg_frame(response, *, received_at_ms: int) -> CapturedFrame:
    headers = _read_headers(response)
    try:
        length = int(headers.get("content-length", ""))
        sequence = int(headers.get("x-thirdhand-sequence", ""))
    except ValueError as error:
        raise FrameCaptureError("invalid_stream", "视觉流缺少有效的帧长度或序号。") from error
    if length < 4 or length > MAX_JPEG_BYTES:
        raise FrameCaptureError("frame_too_large", "视觉帧大小超出允许范围。", retryable=False)
    if sequence < 1:
        raise FrameCaptureError("invalid_stream", "视觉流返回了无效帧序号。")

    jpeg = response.read(length)
    if len(jpeg) != length or not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise FrameCaptureError("invalid_frame", "视觉流返回的内容不是完整 JPEG。")

    source = "mjpeg-delivery"
    captured_at_ms = received_at_ms
    raw_timestamp = headers.get("x-thirdhand-captured-at-ms")
    if raw_timestamp is not None:
        try:
            captured_at_ms = int(raw_timestamp)
        except ValueError as error:
            raise FrameCaptureError("invalid_stream", "视觉流返回了无效采集时间。") from error
        source = "stream-header"
    age_ms = max(0, received_at_ms - captured_at_ms)
    return CapturedFrame(
        jpeg=jpeg,
        sequence=sequence,
        captured_at_ms=captured_at_ms,
        received_at_ms=received_at_ms,
        frame_age_ms=age_ms,
        timestamp_source=source,
    )


class MjpegFrameSource:
    def __init__(
        self,
        url: str,
        *,
        opener: Callable = urlopen,
        clock_ms: Callable[[], int] | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.url = url
        self.opener = opener
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.timeout_seconds = max(0.1, float(timeout_seconds))

    def next_frame(self, previous_sequence: int | None = None) -> CapturedFrame:
        try:
            with self.opener(self.url, timeout=self.timeout_seconds) as response:
                frame = read_mjpeg_frame(response, received_at_ms=int(self.clock_ms()))
        except FrameCaptureError:
            raise
        except Exception as error:
            raise FrameCaptureError(
                "stream_unavailable",
                "当前摄像头画面不可用。",
            ) from error
        if previous_sequence is not None and frame.sequence <= previous_sequence:
            raise FrameCaptureError("frozen_frame", "摄像头画面没有更新。")
        return frame


class ImageRetention:
    def __init__(
        self,
        directory: Path,
        *,
        max_files: int = 20,
        max_age_seconds: int = 24 * 60 * 60,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.directory = Path(directory)
        self.max_files = max(1, int(max_files))
        self.max_age_seconds = max(1, int(max_age_seconds))
        self.clock = clock

    def _cleanup(self, now: float) -> None:
        cutoff = now - self.max_age_seconds
        files = []
        for path in self.directory.glob("*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                else:
                    files.append(path)
            except FileNotFoundError:
                continue
        files.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
        for path in files[self.max_files :]:
            path.unlink(missing_ok=True)

    def save(self, jpeg: bytes, *, sequence: int) -> Path:
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("jpeg must contain a complete JPEG image")
        now = float(self.clock())
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"frame-{int(sequence):06d}-{int(now * 1000)}.jpg"
        path.write_bytes(jpeg)
        path.touch()
        # Use the injected clock for deterministic expiry and ordering.
        import os

        os.utime(path, (now, now))
        self._cleanup(now)
        return path


VISION_SYSTEM_PROMPT = """You are the read-only visual observer for a desktop robot arm.
Answer in the requested language and describe only evidence visible in the supplied image.
State uncertainty for blur, occlusion, unreadable text, brand identity, or ambiguous objects.
Do not invent coordinates, depth, grasp poses, robot actions, or unseen content.
Return a concise natural-language scene description, not JSON."""


def _captured_at_iso(captured_at_ms: int) -> str:
    return (
        datetime.fromtimestamp(captured_at_ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _provider_failure(error: Exception) -> InspectSceneError:
    status = getattr(error, "status_code", None)
    name = type(error).__name__.lower()
    if status in {401, 403} or "authentication" in name or "permission" in name:
        return InspectSceneError(
            "vision_auth_failed",
            "视觉模型鉴权失败，请检查 API 权限。",
            retryable=False,
        )
    if status in {400, 404} or "badrequest" in name or "notfound" in name:
        return InspectSceneError(
            "vision_model_unavailable",
            "视觉模型名称或图片接口不可用。",
            retryable=False,
        )
    retryable = status is None or status == 429 or (isinstance(status, int) and status >= 500)
    return InspectSceneError(
        "vision_model_unavailable",
        "视觉模型暂时不可用。",
        retryable=retryable,
    )


class InspectSceneSkill:
    """Capture one fresh frame and ask DeepSeek Flash for an observation."""

    def __init__(
        self,
        *,
        client,
        frame_source: MjpegFrameSource,
        retention: ImageRetention,
        model: str = "deepseek-flash",
        max_frame_age_ms: int = 2_000,
    ) -> None:
        self.client = client
        self.frame_source = frame_source
        self.retention = retention
        self.model = model
        self.max_frame_age_ms = max(1, int(max_frame_age_ms))
        self._previous_sequence: int | None = None

    def _messages(self, question: str, prior_visual_summary: str | None, language: str):
        context = ""
        if prior_visual_summary:
            context = f"\nPrevious visual summary for reference only: {prior_visual_summary[:2000]}"
        instruction = (
            f"Response language: {'Chinese' if language == 'zh' else 'English'}.\n"
            f"Current visual question: {question[:2000]}{context}"
        )
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": instruction},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": None,
                    },
                },
            ],
        }]

    def _analyze(
        self,
        frame: CapturedFrame,
        *,
        question: str,
        prior_visual_summary: str | None,
        language: str,
    ) -> str:
        messages = self._messages(question, prior_visual_summary, language)
        messages[0]["content"][1]["source"]["data"] = base64.b64encode(frame.jpeg).decode("ascii")
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=VISION_SYSTEM_PROMPT,
                messages=messages,
            )
        except Exception as error:
            raise _provider_failure(error) from error
        parts = [
            str(block.text).strip()
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text" and str(getattr(block, "text", "")).strip()
        ]
        if not parts:
            raise InspectSceneError(
                "vision_empty_response",
                "视觉模型没有返回可用描述。",
                retryable=False,
            )
        return " ".join(parts)

    def invoke(
        self,
        question: str,
        *,
        prior_visual_summary: str | None = None,
        language: str = "zh",
    ) -> dict:
        question = str(question or "").strip()
        if not question:
            raise InspectSceneError("invalid_question", "视觉问题不能为空。", retryable=False)
        if language not in {"zh", "en"}:
            language = "zh"

        last_error: InspectSceneError | None = None
        for attempt in range(2):
            try:
                frame = self.frame_source.next_frame(self._previous_sequence)
                self._previous_sequence = frame.sequence
                if frame.frame_age_ms > self.max_frame_age_ms:
                    raise FrameCaptureError("stale_frame", "摄像头画面已经过期。")
                self.retention.save(frame.jpeg, sequence=frame.sequence)
                summary = self._analyze(
                    frame,
                    question=question,
                    prior_visual_summary=prior_visual_summary,
                    language=language,
                )
                trace = [{
                    "stage": "vision.inspect_scene",
                    "status": "completed",
                    "model": self.model,
                    "frameId": f"xvisio-{frame.sequence}",
                    "sequence": frame.sequence,
                    "frameAgeMs": frame.frame_age_ms,
                    "timestampSource": frame.timestamp_source,
                    "retryCount": attempt,
                }]
                return {
                    "status": "completed",
                    "summary": summary,
                    "frame": {
                        "frameId": f"xvisio-{frame.sequence}",
                        "sequence": frame.sequence,
                        "capturedAt": _captured_at_iso(frame.captured_at_ms),
                        "frameAgeMs": frame.frame_age_ms,
                        "timestampSource": frame.timestamp_source,
                        "widthPx": None,
                        "heightPx": None,
                    },
                    "model": self.model,
                    "trace": trace,
                }
            except FrameCaptureError as error:
                last_error = InspectSceneError(
                    error.code,
                    str(error),
                    retryable=error.retryable,
                )
            except InspectSceneError as error:
                last_error = error
            if attempt == 0 and last_error.retryable:
                continue
            raise last_error
        raise last_error or InspectSceneError(
            "vision_unavailable",
            "视觉功能暂时不可用。",
            retryable=False,
        )


__all__ = [
    "CapturedFrame",
    "FrameCaptureError",
    "ImageRetention",
    "InspectSceneError",
    "InspectSceneSkill",
    "MAX_JPEG_BYTES",
    "MjpegFrameSource",
    "read_mjpeg_frame",
]
