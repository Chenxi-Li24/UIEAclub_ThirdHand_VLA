#!/usr/bin/env python3
"""Read-only D435/Lumos bridge with fail-closed online perception.

stdin accepts only arm_state, get_status, and shutdown JSON lines.
stdout carries D435 debug MJPEG, fd 3 carries JSON events, and fd 4 carries
the canonical Lumos perception overlay. This process never opens robot/CAN.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import Any, Generic, Optional, TypeVar

import cv2
import numpy as np

from vision.camera_models import PinholeCamera
from vision.dual_camera import DualCameraPerception, StampedRobotPose
from vision.identity import PersistentIdentityMemory
from vision.online_frames import DepthFrame, LatestFramePairer
from vision.types import FrameStamp
from vision.calibration_gate import sdk_pose_transform
from vision_models.dino import DinoMaskEncoder
from vision_models.lumos_client import LumosSnapshotClient
from vision_models.online import (
    OnlinePerceptionEngine,
    load_online_vision_config,
    render_overlay,
)
from vision_models.rtmdet import RTMDetInstanceSegmenter


FRAME_WIDTH = 640
FRAME_HEIGHT = 480
JPEG_QUALITY = int(os.environ.get("CAMERA_JPEG_QUALITY", "70"))
VISION_ONLINE_ENABLED = os.environ.get("VISION_ONLINE_ENABLED", "0") == "1"
VISION_CONFIG = Path(
    os.environ.get(
        "VISION_CONFIG",
        str(Path(__file__).resolve().parents[2] / "configs/vision/remind3d.yaml"),
    )
).resolve()
LUMOS_SNAPSHOT_URL = os.environ.get(
    "LUMOS_SNAPSHOT_URL", "http://127.0.0.1:3001/frame.jpg"
)
EVENT_FD = int(os.environ.get("CAMERA_EVENT_FD", "3"))
VISION_OVERLAY_FD = int(os.environ.get("VISION_OVERLAY_FD", "4"))


_event_file = None
_overlay_file = None
_event_lock = threading.Lock()
_overlay_lock = threading.Lock()
shutdown_flag = threading.Event()


def _configure_outputs() -> None:
    global _event_file, _overlay_file
    _event_file = os.fdopen(EVENT_FD, "w", buffering=1, encoding="utf-8", closefd=False)
    if VISION_ONLINE_ENABLED:
        _overlay_file = os.fdopen(VISION_OVERLAY_FD, "wb", buffering=0, closefd=False)


def emit_event(message: dict[str, Any]) -> None:
    if _event_file is None:
        return
    safe = dict(message)
    safe.setdefault("ts", int(time.time() * 1000))
    if safe.get("type") in {"vision_status", "detection_result", "vision_error"}:
        safe["robot_execution_enabled"] = False
    encoded = json.dumps(
        safe,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    with _event_lock:
        print(encoded, file=_event_file, flush=True)


def emit(message_type: str, **payload: Any) -> None:
    emit_event({"type": message_type, **payload})


def _write_mjpeg(stream, jpeg: bytes, lock: threading.Lock) -> None:
    if stream is None:
        return
    with lock:
        stream.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        stream.flush()


T = TypeVar("T")


class LatestValueBuffer(Generic[T]):
    """One-slot condition buffer: consumers can only obtain the newest value."""

    capacity = 1

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._sequence = 0
        self._value: Optional[T] = None

    def publish(self, value: T) -> int:
        with self._condition:
            self._sequence += 1
            self._value = value
            self._condition.notify_all()
            return self._sequence

    def get_after(self, sequence: int, timeout_s: float) -> Optional[tuple[int, T]]:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while self._sequence <= sequence and not shutdown_flag.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return None
                self._condition.wait(remaining)
            if self._sequence <= sequence or self._value is None:
                return None
            return self._sequence, self._value


def depth_to_metres(raw_depth: Any, depth_scale: float) -> np.ndarray:
    raw = np.asarray(raw_depth)
    scale = float(depth_scale)
    if raw.ndim != 2 or raw.dtype != np.uint16:
        raise ValueError("D435 depth must be a uint16 2D image")
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError("D435 depth scale must be finite and positive")
    depth = raw.astype(np.float32) * np.float32(scale)
    depth[raw == 0] = np.nan
    depth.setflags(write=False)
    return depth


def accepted_command_type(message: Any) -> Optional[str]:
    if not isinstance(message, dict):
        return None
    command = message.get("type") or message.get("cmd")
    return command if command in {"arm_state", "get_status", "shutdown"} else None


@dataclass(frozen=True)
class D435Sample:
    depth: DepthFrame
    camera: PinholeCamera
    debug_jpeg: bytes
    depth_scale: float


@dataclass(frozen=True)
class ArmPoseSample:
    stamp: FrameStamp
    transform: np.ndarray


d435_latest: LatestValueBuffer[D435Sample] = LatestValueBuffer()
arm_pose_latest: LatestValueBuffer[ArmPoseSample] = LatestValueBuffer()
_state_lock = threading.Lock()
_state: dict[str, Any] = {
    "d435_ready": False,
    "d435_sequence": 0,
    "lumos_sequence": 0,
    "model_ready": False,
    "vision_online": False,
    "vision_error": None,
}


def _update_state(**values: Any) -> None:
    with _state_lock:
        _state.update(values)


def _state_snapshot() -> dict[str, Any]:
    with _state_lock:
        return dict(_state)


def _d435_debug_frame(frame_bgr: np.ndarray, raw_depth: np.ndarray, sequence: int) -> bytes:
    output = np.array(frame_bgr, copy=True)
    depth_viz = np.clip(raw_depth.astype(np.float32) / 3000.0 * 255.0, 0, 255).astype(
        np.uint8
    )
    depth_viz = cv2.applyColorMap(depth_viz, cv2.COLORMAP_JET)
    depth_viz[raw_depth == 0] = 0
    depth_small = cv2.resize(depth_viz, (160, 120))
    output[-120:, -160:] = depth_small
    cv2.putText(
        output,
        f"D435 RGB debug | metric depth | seq {sequence}",
        (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 255, 0),
        1,
        cv2.LINE_AA,
    )
    ok, encoded = cv2.imencode(
        ".jpg", output, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    )
    if not ok:
        raise RuntimeError("D435 debug JPEG encoding failed")
    return encoded.tobytes()


def capture_d435() -> None:
    """Own the D435 exactly once and publish aligned depth in metres."""

    pipeline = None
    try:
        import pyrealsense2 as rs

        pipeline = rs.pipeline()
        stream_config = rs.config()
        stream_config.enable_stream(
            rs.stream.depth, FRAME_WIDTH, FRAME_HEIGHT, rs.format.z16, 30
        )
        stream_config.enable_stream(
            rs.stream.color, FRAME_WIDTH, FRAME_HEIGHT, rs.format.bgr8, 30
        )
        profile = pipeline.start(stream_config)
        device = profile.get_device()
        serial = device.get_info(rs.camera_info.serial_number)
        depth_scale = float(device.first_depth_sensor().get_depth_scale())
        color_profile = profile.get_stream(rs.stream.color).as_video_stream_profile()
        intrinsics = color_profile.get_intrinsics()
        camera = PinholeCamera(
            intrinsics.fx,
            intrinsics.fy,
            intrinsics.ppx,
            intrinsics.ppy,
            intrinsics.width,
            intrinsics.height,
        )
        align = rs.align(rs.stream.color)
        for _ in range(15):
            if shutdown_flag.is_set():
                return
            pipeline.wait_for_frames(timeout_ms=1000)
        _update_state(d435_ready=True, d435_serial=serial, depth_scale=depth_scale)
        emit(
            "camera_status",
            d435_ready=True,
            d435_serial=serial,
            d435_rgb_role="debug_only",
            d435_depth_role="metric_depth",
            depth_scale=depth_scale,
            resolution=[FRAME_WIDTH, FRAME_HEIGHT],
            calibration_validated=False,
        )
        frame_id = 0
        while not shutdown_flag.is_set():
            frames = align.process(pipeline.wait_for_frames(timeout_ms=1000))
            color = frames.get_color_frame()
            depth = frames.get_depth_frame()
            if not color or not depth:
                continue
            frame_id += 1
            monotonic_ns = time.monotonic_ns()
            frame_bgr = np.array(np.asanyarray(color.get_data()), copy=True)
            raw_depth = np.array(np.asanyarray(depth.get_data()), dtype=np.uint16, copy=True)
            depth_m = depth_to_metres(raw_depth, depth_scale)
            debug_jpeg = _d435_debug_frame(frame_bgr, raw_depth, frame_id)
            sample = D435Sample(
                depth=DepthFrame(
                    FrameStamp("d435_depth", frame_id, monotonic_ns), depth_m
                ),
                camera=camera,
                debug_jpeg=debug_jpeg,
                depth_scale=depth_scale,
            )
            sequence = d435_latest.publish(sample)
            _update_state(d435_sequence=sequence)
            _write_mjpeg(sys.stdout.buffer, debug_jpeg, _overlay_lock)
    except Exception as error:
        _update_state(d435_ready=False, vision_online=False, vision_error=str(error))
        emit("camera_error", message=f"D435 capture failed: {error}")
        traceback.print_exc(file=sys.stderr)
    finally:
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception:
                pass
        _update_state(d435_ready=False)


def _load_online_engine():
    config = load_online_vision_config(VISION_CONFIG)
    emit(
        "vision_status",
        online=False,
        phase="loading_models",
        canonical_rgb_source=config.roles.canonical_rgb_source,
        metric_depth_source=config.roles.metric_depth_source,
        task_checkpoint_validated=config.task_checkpoint_validated,
        blockers=["model_loading", "calibration_unavailable"],
    )
    segmenter = RTMDetInstanceSegmenter(
        config.detector_config_path,
        config.detector_checkpoint_path,
        config.detector_labels,
        device=config.detector_device,
        min_score=config.detector_min_score,
    )
    encoder = DinoMaskEncoder(
        model_id=config.descriptor_model_id,
        device=config.descriptor_device,
        min_patch_coverage=config.min_patch_coverage,
        max_long_side=config.dino_max_long_side,
    )
    perception = DualCameraPerception(
        PersistentIdentityMemory(config.identity_config), config.perception_config
    )
    return config, OnlinePerceptionEngine(segmenter, encoder, perception, config)


def run_online_perception() -> None:
    """Read newest Lumos frame, pair newest D435 depth, and emit read-only output."""

    try:
        config, engine = _load_online_engine()
        pairer = LatestFramePairer(
            config.roles,
            config.perception_config.max_frame_skew_ns,
            config.perception_config.max_frame_age_ns,
        )
        lumos = LumosSnapshotClient(LUMOS_SNAPSHOT_URL, timeout_s=1.0)
    except Exception as error:
        _update_state(model_ready=False, vision_online=False, vision_error=str(error))
        emit(
            "vision_error",
            message=f"online model initialization failed: {error}",
            blockers=["model_unavailable"],
        )
        traceback.print_exc(file=sys.stderr)
        return

    _update_state(model_ready=True, vision_error=None)
    last_lumos_sequence = -1
    last_d435_sequence = 0
    backoff_s = 0.1
    while not shutdown_flag.is_set():
        try:
            rgb = lumos.read(last_lumos_sequence)
            if rgb is None:
                time.sleep(0.01)
                continue
            last_lumos_sequence = rgb.stamp.frame_id
            d435_item = d435_latest.get_after(last_d435_sequence, timeout_s=0.0)
            depth = None
            if d435_item is not None:
                last_d435_sequence, d435 = d435_item
                depth = d435.depth
            now_ns = time.monotonic_ns()
            pair = pairer.pair(rgb, depth, now_ns)
            arm_item = arm_pose_latest.get_after(0, timeout_s=0.0)
            robot_pose = None
            if arm_item is not None:
                _, arm = arm_item
                if now_ns - arm.stamp.monotonic_ns <= 250_000_000:
                    robot_pose = StampedRobotPose(arm.stamp, arm.transform)
            # The current real cross-camera calibration is unvalidated. Passing None is
            # intentional: identity/overlay remain online but all targets stay blocked.
            result = engine.process(
                pair,
                robot_pose=robot_pose,
                calibration=None,
                arm_stationary=False,
                now_ns=now_ns,
            )
            event = result.to_event()
            emit_event(event)
            blockers = list(result.blockers)
            if "calibration_unavailable" not in blockers:
                blockers.append("calibration_unavailable")
            _update_state(
                lumos_sequence=last_lumos_sequence,
                model_ready=result.model_ready,
                vision_online=True,
                vision_error=result.model_error,
            )
            emit(
                "vision_status",
                online=True,
                model_ready=result.model_ready,
                canonical_rgb_source=result.canonical_rgb_source,
                metric_depth_source=result.metric_depth_source,
                lumos_sequence=last_lumos_sequence,
                d435_sequence=last_d435_sequence,
                latency_ms=result.latency_ms,
                latency_p95_ms=result.latency_p95_ms,
                gpu_memory_reserved_gib=result.gpu_memory_reserved_gib,
                task_checkpoint_validated=result.task_checkpoint_validated,
                blockers=blockers,
            )
            overlay_rgb = render_overlay(rgb.image_rgb, result)
            ok, encoded = cv2.imencode(
                ".jpg",
                cv2.cvtColor(overlay_rgb, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
            )
            if not ok:
                raise RuntimeError("Lumos overlay JPEG encoding failed")
            _write_mjpeg(_overlay_file, encoded.tobytes(), _overlay_lock)
            backoff_s = 0.1
        except Exception as error:
            _update_state(vision_online=False, vision_error=str(error))
            emit(
                "vision_error",
                message=f"online frame failed: {error}",
                blockers=["vision_unavailable"],
            )
            time.sleep(backoff_s)
            backoff_s = min(2.0, backoff_s * 2.0)


def _handle_arm_state(command: dict[str, Any]) -> None:
    position = command.get("tcp_position_m") or command.get("position")
    euler = command.get("tcp_euler_rad") or command.get("euler")
    if not isinstance(position, list) or not isinstance(euler, list):
        return
    if len(position) != 3 or len(euler) != 3:
        return
    values = np.asarray([*position, *euler], dtype=float)
    if not np.isfinite(values).all():
        return
    stamp_ns = time.monotonic_ns()
    sequence = arm_pose_latest.publish(
        ArmPoseSample(
            FrameStamp("robot_flange_pose", stamp_ns, stamp_ns),
            sdk_pose_transform(values[:3], values[3:]),
        )
    )
    _update_state(robot_pose_sequence=sequence)


def main() -> None:
    _configure_outputs()
    capture_thread = threading.Thread(target=capture_d435, daemon=True)
    capture_thread.start()
    online_thread = None
    if VISION_ONLINE_ENABLED:
        online_thread = threading.Thread(target=run_online_perception, daemon=True)
        online_thread.start()
    emit(
        "bridge_ready",
        source="camera_bridge",
        vision_online_enabled=VISION_ONLINE_ENABLED,
        canonical_rgb_source="lumos_rgb",
        metric_depth_source="d435_depth",
    )

    for line in sys.stdin:
        if shutdown_flag.is_set():
            break
        try:
            command = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        command_type = accepted_command_type(command)
        if command_type == "arm_state":
            _handle_arm_state(command)
        elif command_type == "get_status":
            emit("camera_status", **_state_snapshot())
        elif command_type == "shutdown":
            shutdown_flag.set()
            break

    shutdown_flag.set()
    capture_thread.join(timeout=3.0)
    if online_thread is not None:
        online_thread.join(timeout=3.0)


if __name__ == "__main__":
    main()
