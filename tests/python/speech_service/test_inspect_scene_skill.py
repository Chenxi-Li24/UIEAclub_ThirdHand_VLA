from __future__ import annotations

from io import BytesIO
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
WORKER = ROOT / "skills" / "vision" / "inspect-scene" / "src" / "worker.py"


def load_worker():
    assert WORKER.is_file(), "inspect-scene worker is missing"
    spec = importlib.util.spec_from_file_location("inspect_scene_worker", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mjpeg_part(jpeg: bytes, *, sequence: int, captured_at_ms: int | None = None) -> bytes:
    headers = [
        b"--frame\r\n",
        b"Content-Type: image/jpeg\r\n",
        f"Content-Length: {len(jpeg)}\r\n".encode("ascii"),
        f"X-ThirdHand-Sequence: {sequence}\r\n".encode("ascii"),
    ]
    if captured_at_ms is not None:
        headers.append(f"X-ThirdHand-Captured-At-Ms: {captured_at_ms}\r\n".encode("ascii"))
    return b"".join(headers) + b"\r\n" + jpeg + b"\r\n"


class Response:
    def __init__(self, payload: bytes):
        self.stream = BytesIO(payload)

    def readline(self, size: int = -1) -> bytes:
        return self.stream.readline(size)

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_parses_jpeg_sequence_and_source_timestamp():
    worker = load_worker()
    jpeg = b"\xff\xd8scene\xff\xd9"

    frame = worker.read_mjpeg_frame(
        Response(mjpeg_part(jpeg, sequence=42, captured_at_ms=9_900)),
        received_at_ms=10_000,
    )

    assert frame.jpeg == jpeg
    assert frame.sequence == 42
    assert frame.captured_at_ms == 9_900
    assert frame.frame_age_ms == 100
    assert frame.timestamp_source == "stream-header"


def test_marks_delivery_time_fallback_explicitly():
    worker = load_worker()
    frame = worker.read_mjpeg_frame(
        Response(mjpeg_part(b"\xff\xd8x\xff\xd9", sequence=7)),
        received_at_ms=12_345,
    )

    assert frame.captured_at_ms == 12_345
    assert frame.frame_age_ms == 0
    assert frame.timestamp_source == "mjpeg-delivery"


def test_rejects_repeated_sequence_as_frozen():
    worker = load_worker()
    source = worker.MjpegFrameSource(
        "http://127.0.0.1:3100/camera/xvisio/raw",
        opener=lambda *_args, **_kwargs: Response(
            mjpeg_part(b"\xff\xd8x\xff\xd9", sequence=11)
        ),
        clock_ms=lambda: 20_000,
    )

    with pytest.raises(worker.FrameCaptureError) as error:
        source.next_frame(previous_sequence=11)

    assert error.value.code == "frozen_frame"
    assert "http" not in str(error.value).lower()


def test_rejects_oversized_or_invalid_jpeg():
    worker = load_worker()
    oversized = (
        b"--frame\r\nContent-Type: image/jpeg\r\n"
        + f"Content-Length: {worker.MAX_JPEG_BYTES + 1}\r\n".encode("ascii")
        + b"X-ThirdHand-Sequence: 1\r\n\r\n"
    )
    with pytest.raises(worker.FrameCaptureError) as too_large:
        worker.read_mjpeg_frame(Response(oversized), received_at_ms=1)
    assert too_large.value.code == "frame_too_large"

    invalid = mjpeg_part(b"not-a-jpeg", sequence=2)
    with pytest.raises(worker.FrameCaptureError) as bad_jpeg:
        worker.read_mjpeg_frame(Response(invalid), received_at_ms=1)
    assert bad_jpeg.value.code == "invalid_frame"


def test_retention_keeps_twenty_recent_jpegs_and_expires_old_files(tmp_path: Path):
    worker = load_worker()
    now = 200_000.0
    retention = worker.ImageRetention(
        tmp_path,
        max_files=20,
        max_age_seconds=24 * 60 * 60,
        clock=lambda: now,
    )
    old = tmp_path / "old.jpg"
    old.write_bytes(b"old")
    os.utime(old, (now - 90_000, now - 90_000))

    for sequence in range(1, 23):
        retention.save(b"\xff\xd8x\xff\xd9", sequence=sequence)

    files = sorted(tmp_path.glob("*.jpg"), key=lambda path: path.stat().st_mtime)
    assert len(files) == 20
    assert not old.exists()
    assert not any("000001" in path.name or "000002" in path.name for path in files)


class FrameSource:
    def __init__(self, worker, outcomes):
        self.worker = worker
        self.outcomes = list(outcomes)
        self.calls = []

    def next_frame(self, previous_sequence=None):
        self.calls.append(previous_sequence)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Retention:
    def __init__(self):
        self.saved = []

    def save(self, jpeg, *, sequence):
        self.saved.append((jpeg, sequence))
        return Path(f"/tmp/frame-{sequence}.jpg")


class Messages:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if hasattr(outcome, "content"):
            return outcome
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=outcome)],
            stop_reason="end_turn",
        )


class Client:
    def __init__(self, outcomes):
        self.messages = Messages(outcomes)


def captured(worker, sequence=21, age_ms=20):
    now = 50_000
    return worker.CapturedFrame(
        jpeg=b"\xff\xd8scene\xff\xd9",
        sequence=sequence,
        captured_at_ms=now - age_ms,
        received_at_ms=now,
        frame_age_ms=age_ms,
        timestamp_source="stream-header",
    )


def test_flash_request_contains_only_question_context_and_jpeg():
    worker = load_worker()
    client = Client(["桌面上有一个红色饮料罐。"])
    source = FrameSource(worker, [captured(worker)])
    retention = Retention()
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=retention,
        model="deepseek-flash",
    )

    result = skill.invoke(
        "前面有什么？",
        prior_visual_summary="上一帧里有一个罐子。",
        language="zh",
    )

    assert result["status"] == "completed"
    assert result["summary"] == "桌面上有一个红色饮料罐。"
    assert result["model"] == "deepseek-flash"
    assert result["frame"]["sequence"] == 21
    assert retention.saved == [(captured(worker).jpeg, 21)]
    request = client.messages.calls[0]
    assert request["model"] == "deepseek-flash"
    assert request["max_tokens"] == 1024
    content = request["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "前面有什么" in content[0]["text"]
    assert "上一帧里有一个罐子" in content[0]["text"]
    assert content[1]["type"] == "image"
    assert content[1]["source"]["type"] == "base64"
    assert content[1]["source"]["media_type"] == "image/jpeg"


def test_visual_request_allows_enough_output_budget_for_final_text():
    worker = load_worker()

    class BudgetSensitiveMessages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["max_tokens"] < 1024:
                return SimpleNamespace(
                    content=[SimpleNamespace(type="thinking", thinking="reasoning")],
                    stop_reason="max_tokens",
                )
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="桌面上还有一块黄色物体。")],
                stop_reason="end_turn",
            )

    client = SimpleNamespace(messages=BudgetSensitiveMessages())
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=FrameSource(worker, [captured(worker, 60)]),
        retention=Retention(),
    )

    result = skill.invoke("除了刚才说的，还有什么？", language="zh")

    assert result["summary"] == "桌面上还有一块黄色物体。"
    assert len(client.messages.calls) == 1


def test_retries_empty_max_token_response_once_with_a_new_frame():
    worker = load_worker()
    empty = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="reasoning")],
        stop_reason="max_tokens",
    )
    success = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="第二帧返回了描述。")],
        stop_reason="end_turn",
    )
    source = FrameSource(worker, [captured(worker, 61), captured(worker, 62)])
    client = Client([empty, success])
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=Retention(),
    )

    result = skill.invoke("再看一下", language="zh")

    assert result["summary"] == "第二帧返回了描述。"
    assert result["frame"]["sequence"] == 62
    assert result["trace"][-1]["retryCount"] == 1
    assert len(client.messages.calls) == 2


def test_two_empty_visual_responses_fail_after_one_retry():
    worker = load_worker()
    empty = SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="reasoning")],
        stop_reason="max_tokens",
    )
    source = FrameSource(worker, [captured(worker, 63), captured(worker, 64)])
    client = Client([empty, empty])
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=Retention(),
    )

    with pytest.raises(worker.InspectSceneError) as error:
        skill.invoke("再看一次", language="zh")

    assert error.value.code == "vision_empty_response"
    assert len(client.messages.calls) == 2
    assert len(source.calls) == 2


def test_retries_one_transient_capture_failure_with_a_new_frame():
    worker = load_worker()
    transient = worker.FrameCaptureError("stream_unavailable", "不可用", retryable=True)
    source = FrameSource(worker, [transient, captured(worker, sequence=31)])
    client = Client(["看到了桌面。"])
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=Retention(),
    )

    result = skill.invoke("重新看一下", language="zh")

    assert result["status"] == "completed"
    assert len(source.calls) == 2
    assert result["trace"][-1]["retryCount"] == 1


def test_retries_one_transient_provider_failure_and_fetches_a_new_frame():
    worker = load_worker()
    source = FrameSource(worker, [captured(worker, 40), captured(worker, 41)])
    client = Client([TimeoutError("secret transport detail"), "第二次成功。"])
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=Retention(),
    )

    result = skill.invoke("看一下", language="zh")

    assert result["summary"] == "第二次成功。"
    assert len(client.messages.calls) == 2
    assert result["frame"]["sequence"] == 41
    assert "secret" not in str(result["trace"]).lower()


def test_authentication_failure_does_not_retry_or_fall_back():
    worker = load_worker()

    class AuthenticationError(Exception):
        status_code = 401

    source = FrameSource(worker, [captured(worker)])
    client = Client([AuthenticationError("api_key=never-log-this")])
    skill = worker.InspectSceneSkill(
        client=client,
        frame_source=source,
        retention=Retention(),
    )

    with pytest.raises(worker.InspectSceneError) as error:
        skill.invoke("看一下", language="zh")

    assert error.value.code == "vision_auth_failed"
    assert error.value.retryable is False
    assert len(client.messages.calls) == 1
    assert "never-log" not in str(error.value)
    assert all(call["model"] == "deepseek-flash" for call in client.messages.calls)


def test_two_stale_frames_fail_explicitly_after_one_retry():
    worker = load_worker()
    source = FrameSource(
        worker,
        [captured(worker, 50, age_ms=2_001), captured(worker, 51, age_ms=3_000)],
    )
    skill = worker.InspectSceneSkill(
        client=Client(["must not be called"]),
        frame_source=source,
        retention=Retention(),
        max_frame_age_ms=2_000,
    )

    with pytest.raises(worker.InspectSceneError) as error:
        skill.invoke("前面有什么", language="zh")

    assert error.value.code == "stale_frame"
    assert len(source.calls) == 2
    assert skill.client.messages.calls == []
