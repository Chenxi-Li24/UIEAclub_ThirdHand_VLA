import importlib.util
import io
import json
import queue
from pathlib import Path
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from thirdhand_va.common.contracts import VisionDecision


def load_script():
    path = Path("apps/bottle_pick/camera_bridge.py")
    spec = importlib.util.spec_from_file_location("camera_bridge_va", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_is_side_effect_free_and_live_requires_explicit_camera_permission(
    monkeypatch,
) -> None:
    monkeypatch.delenv("THIRDHAND_VA_ALLOW_CAMERA", raising=False)
    module = load_script()
    args = module.build_parser().parse_args([])

    with pytest.raises(RuntimeError, match="camera access is disabled"):
        module.assert_camera_access(args)


def test_replay_mode_never_requires_camera_permission() -> None:
    module = load_script()
    args = module.build_parser().parse_args(
        [
            "--source", "replay", "--bundles", "saved-frame",
        ]
    )

    module.assert_camera_access(args)


def test_parser_uses_single_lumos_environment_defaults(monkeypatch) -> None:
    monkeypatch.setenv("THIRDHAND_VA_CONFIG", "/tmp/vision.yaml")
    monkeypatch.setenv("THIRDHAND_VA_HANDEYE", "/tmp/handeye.json")
    monkeypatch.setenv("XVISIO_STREAM_EXECUTABLE", "/tmp/xvisio_rgbd_stream")
    module = load_script()

    args = module.build_parser().parse_args([])

    assert not hasattr(args, "selection_side")
    assert not hasattr(args, "ordinal")
    assert str(args.config) == "/tmp/vision.yaml"
    assert str(args.executable) == "/tmp/xvisio_rgbd_stream"
    assert str(args.handeye) == "/tmp/handeye.json"


def test_bridge_ready_handshake_keeps_robot_control_disabled() -> None:
    module = load_script()
    stream = io.BytesIO()
    config = module.VisionConfig.from_yaml("configs/vision.yaml")
    provenance = {
        "vision_config_id": config.content_id,
        "grounding_revision": "1" * 40,
        "grounding_weights_sha256": "sha256:" + "a" * 64,
        "sam_revision": "2" * 40,
        "sam_weights_sha256": "sha256:" + "b" * 64,
    }

    module.emit_bridge_ready(stream, config, None, provenance)

    event = json.loads(stream.getvalue())
    assert event == {
        "type": "bridge_ready",
        "camera": "xvisio_rgbd",
        "camera_serial": config.camera_serial,
        "registration_id": config.camera_registration_id,
        "camera_mount_id": config.camera_mount_id,
        "vision_config_id": config.content_id,
        "calibration_id": None,
        "calibration_approved": False,
        "model_provenance": provenance,
        "robot_control_enabled": False,
    }


def test_vision_status_reports_live_xvisio_rgbd_after_inference() -> None:
    """Removing status emission must make the control site look offline again."""
    module = load_script()
    stream = io.BytesIO()
    decision = VisionDecision(
        status="searching",
        frame_id=42,
        target=None,
        pose=None,
        reasons=("target_not_found",),
        stable_hits=0,
        window_size=5,
        captured_monotonic_ns=123_000,
        camera_serial="250801DR48FP25002738",
        registration_id="xvisio-sdk:250801DR48FP25002738",
        motion_epoch=2,
        evidence_id="sha256:" + "a" * 64,
    )
    provenance = module.FrameProvenance(
        frame_id=42,
        monotonic_ns=123_000,
        observed_at_ms=456_000,
    )

    module.emit_vision_status(stream, decision, provenance, latency_ms=12.5)

    event = json.loads(stream.getvalue())
    assert event == {
        "type": "vision_status",
        "ts": 456_000,
        "online": True,
        "model_ready": True,
        "camera_ready": True,
        "canonical_rgb_source": "xvisio_rgb",
        "metric_depth_source": "xvisio_depth",
        "lumos_sequence": 42,
        "registration_id": "xvisio-sdk:250801DR48FP25002738",
        "motion_epoch": 2,
        "latency_ms": 12.5,
        "blockers": ["target_not_found"],
        "robot_control_enabled": False,
    }


def test_command_consumer_accepts_structured_voice_selection(monkeypatch) -> None:
    module = load_script()
    commands = io.StringIO(
        '{"type":"select_bottle","stable_id":2,"request_id":"voice-7"}\n'
        '{"type":"reset_target_pose_reference","request_id":"voice-7",'
        '"motion_epoch":3}\n'
        '{"type":"release_bottle","request_id":"voice-7"}\n'
    )
    monkeypatch.setattr(module.sys, "stdin", commands)
    selections = queue.SimpleQueue()
    pose_resets = queue.SimpleQueue()
    releases = queue.SimpleQueue()

    module.consume_commands(module.ArmStateStore(), selections, pose_resets, releases)

    stable_id, request_id = selections.get_nowait()
    assert (stable_id, request_id) == (2, "voice-7")
    assert pose_resets.get_nowait() == ("voice-7", 3)
    assert releases.get_nowait() == "voice-7"


def test_pending_selection_retries_until_the_stable_track_exists() -> None:
    """Dropping a request after one early miss must break this regression."""
    module = load_script()

    class DelayedPipeline:
        def __init__(self) -> None:
            self.selection = None
            self.attempts = 0

        def select(self, stable_id: int, request_id: str) -> bool:
            self.attempts += 1
            if self.attempts < 2:
                return False
            self.selection = SimpleNamespace(
                stable_id=stable_id,
                request_id=request_id,
            )
            return True

    pipeline = DelayedPipeline()
    controller = module.PendingSelectionController()
    controller.submit(2, "voice-7")

    assert controller.try_apply(pipeline) == {
        "type": "selection_status",
        "request_id": "voice-7",
        "stable_id": 2,
        "status": "pending",
        "changed": False,
        "robot_control_enabled": False,
    }
    assert controller.try_apply(pipeline) == {
        "type": "selection_status",
        "request_id": "voice-7",
        "stable_id": 2,
        "status": "accepted",
        "changed": True,
        "robot_control_enabled": False,
    }
    assert pipeline.attempts == 2
    assert controller.try_apply(pipeline) is None


def test_release_cancels_a_selection_that_is_still_pending() -> None:
    """A cancelled workflow must never reserve its old bottle later."""
    module = load_script()

    class UnreadyPipeline:
        selection = None

        def __init__(self) -> None:
            self.select_calls = 0
            self.release_calls = []

        def select(self, stable_id: int, request_id: str) -> bool:
            self.select_calls += 1
            return False

        def release(self, request_id: str) -> None:
            self.release_calls.append(request_id)

    pipeline = UnreadyPipeline()
    controller = module.PendingSelectionController()
    controller.submit(4, "voice-9")
    assert controller.try_apply(pipeline)["status"] == "pending"

    assert controller.release(pipeline, "voice-9") == {
        "type": "selection_release_status",
        "request_id": "voice-9",
        "status": "released",
        "robot_control_enabled": False,
    }
    assert controller.try_apply(pipeline) is None
    assert pipeline.select_calls == 1
    assert pipeline.release_calls == ["voice-9"]


def test_capture_publishes_all_preview_frames_without_waiting_for_inference() -> None:
    """Removing the capture worker must make raw/depth previews stall again."""
    module = load_script()
    frames = [
        module.RgbdFrame(
            sequence=sequence,
            monotonic_ns=sequence * 1_000,
            camera_serial="camera-serial",
            rgb=np.full((4, 6, 3), 40 + sequence, dtype=np.uint8),
            depth_m=np.full((4, 6), 0.5, dtype=np.float32),
            xyz_camera_m=np.zeros((4, 6, 3), dtype=np.float32),
        )
        for sequence in (1, 2)
    ]
    mailbox = module.LatestFrameMailbox()
    raw_stream = io.BytesIO()
    depth_stream = io.BytesIO()
    worker = module.start_capture_worker(
        frames=iter(frames),
        mailbox=mailbox,
        raw_stream=raw_stream,
        depth_stream=depth_stream,
        min_depth_m=0.2,
        max_depth_m=1.2,
        stop=threading.Event(),
    )

    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert raw_stream.getvalue().count(b"--frame\r\n") == 2
    assert depth_stream.getvalue().count(b"--frame\r\n") == 2
    assert mailbox.wait_for_newer(-1, timeout_s=0.0).sequence == 2
    assert mailbox.wait_for_newer(2, timeout_s=0.0) is None


def test_stop_capture_worker_closes_a_blocked_frame_source() -> None:
    module = load_script()

    class BlockingFrames:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.closed = threading.Event()

        def __iter__(self):
            return self

        def __next__(self):
            self.entered.set()
            self.closed.wait()
            raise StopIteration

        def close(self) -> None:
            self.closed.set()

    frames = BlockingFrames()
    mailbox = module.LatestFrameMailbox()
    stop = threading.Event()
    worker = module.start_capture_worker(
        frames=frames,
        mailbox=mailbox,
        raw_stream=io.BytesIO(),
        depth_stream=io.BytesIO(),
        min_depth_m=0.2,
        max_depth_m=1.2,
        stop=stop,
    )
    assert frames.entered.wait(timeout=1.0)

    module.stop_capture_worker(
        frames=frames,
        mailbox=mailbox,
        stop=stop,
        worker=worker,
        timeout_s=1.0,
    )

    assert frames.closed.is_set()
    assert not worker.is_alive()


def test_capture_error_preserves_the_root_cause() -> None:
    module = load_script()
    mailbox = module.LatestFrameMailbox()
    mailbox.close(ValueError("native RGB-D timeout"))

    with pytest.raises(RuntimeError, match="native RGB-D timeout"):
        mailbox.wait_for_newer(-1, timeout_s=0.0)


def test_preview_encode_failure_is_reported_and_capture_continues(monkeypatch) -> None:
    module = load_script()
    original = module.encode_jpeg
    calls = 0

    def flaky_encode(image):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("fixture encode failure")
        return original(image)

    monkeypatch.setattr(module, "encode_jpeg", flaky_encode)
    frames = [
        module.RgbdFrame(
            sequence=sequence,
            monotonic_ns=sequence * 1_000,
            camera_serial="camera-serial",
            rgb=np.full((8, 10, 3), 40 + sequence, dtype=np.uint8),
            depth_m=np.full((8, 10), 0.5, dtype=np.float32),
            xyz_camera_m=np.zeros((8, 10, 3), dtype=np.float32),
        )
        for sequence in (1, 2)
    ]
    mailbox = module.LatestFrameMailbox()
    errors = io.BytesIO()
    worker = module.start_capture_worker(
        frames=iter(frames),
        mailbox=mailbox,
        raw_stream=io.BytesIO(),
        depth_stream=io.BytesIO(),
        error_stream=errors,
        min_depth_m=0.2,
        max_depth_m=1.2,
        stop=threading.Event(),
    )

    worker.join(timeout=2.0)

    assert not worker.is_alive()
    assert mailbox.wait_for_newer(-1, timeout_s=0.0).sequence == 2
    events = [json.loads(line) for line in errors.getvalue().splitlines()]
    assert events[0]["type"] == "preview_encode_failed"
    assert events[0]["frame_id"] == 1
