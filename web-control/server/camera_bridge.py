#!/usr/bin/env python3
"""Read-only D435/Lumos bridge with fail-closed online perception.

stdin accepts only arm_state, get_status, and shutdown JSON lines.
stdout carries D435 debug MJPEG, fd 3 carries JSON events, and fd 4 carries
the canonical Lumos perception overlay. This process never opens robot/CAN.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import traceback
from typing import Any, Generic, Optional, TypeVar
from uuid import UUID

import cv2
import numpy as np

from vision.camera_models import PinholeCamera
from vision.capture_provenance import FrameStampSequencer
from vision.dual_camera import DualCameraPerception, StampedRobotPose
from vision.identity import PersistentIdentityMemory
from vision.online_frames import DepthFrame, LatestFramePairer
from vision.types import FrameStamp
from vision.calibration_gate import sdk_pose_transform
from vision.active_view_session import ActiveViewPhase, ActiveViewSessionCoordinator
from vision_models.dino import DinoMaskEncoder
from vision_models.active_view_online import (
    ActiveViewDryRunAdapter,
    load_active_view_config,
)
from vision_models.lumos_client import LumosSnapshotClient
from vision_models.active_view_catalog import (
    ActiveViewEvidenceError,
    ActiveViewEvidenceGuard,
)
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
ACTIVE_VIEW_CONFIG = Path(
    os.environ.get(
        "ACTIVE_VIEW_CONFIG",
        str(Path(__file__).resolve().parents[2] / "configs/vision/active_view.yaml"),
    )
).resolve()
ACTIVE_VIEW_EVIDENCE_DIR = Path(
    os.environ.get(
        "ACTIVE_VIEW_EVIDENCE_DIR",
        str(Path(__file__).resolve().parents[2] / "data/calibration/active-view"),
    )
).resolve()
ACTIVE_VIEW_CAMERA_EVIDENCE = Path(
    os.environ.get(
        "ACTIVE_VIEW_CAMERA_EVIDENCE",
        str(ACTIVE_VIEW_EVIDENCE_DIR / "camera.json"),
    )
).resolve()
ACTIVE_VIEW_TABLE_EVIDENCE = Path(
    os.environ.get(
        "ACTIVE_VIEW_TABLE_EVIDENCE",
        str(ACTIVE_VIEW_EVIDENCE_DIR / "table.json"),
    )
).resolve()
ACTIVE_VIEW_CATALOG = Path(
    os.environ.get(
        "ACTIVE_VIEW_CATALOG",
        str(ACTIVE_VIEW_EVIDENCE_DIR / "catalog.json"),
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
_d435_output_lock = threading.Lock()
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
        safe["active_view_execution_enabled"] = False
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


class ActiveViewCommandMailbox:
    """FIFO handoff; only the online perception thread drains commands."""

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()

    def publish(self, command: dict[str, Any]) -> None:
        self._queue.put(dict(command))

    def drain(self) -> tuple[dict[str, Any], ...]:
        commands: list[dict[str, Any]] = []
        while True:
            try:
                commands.append(self._queue.get_nowait())
            except queue.Empty:
                return tuple(commands)


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


SESSION_COMMAND_KEYS = {
    "active_view_start": {"type", "session_id", "identity_id"},
    "active_view_motion_started": {
        "type",
        "session_id",
        "proposal_id",
        "request_id",
    },
    "active_view_motion_completed": {"type", "session_id", "request_id"},
    "active_view_motion_failed": {"type", "session_id", "request_id", "reason"},
    "active_view_cancel": {"type", "session_id"},
    "active_view_operator_confirmed": {"type", "session_id", "proposal_id"},
}


def _canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def accepted_command_type(message: Any) -> Optional[str]:
    if not isinstance(message, dict):
        return None
    command = message.get("type") or message.get("cmd")
    if command == "arm_state":
        return command if set(message) == ARM_STATE_KEYS else None
    if command in {"get_status", "shutdown"}:
        return command if set(message) in ({"cmd"}, {"type"}) else None
    expected = SESSION_COMMAND_KEYS.get(command)
    if expected is None or set(message) != expected:
        return None
    id_fields = ("session_id", "proposal_id", "request_id")
    if any(field in message and not _canonical_uuid(message[field]) for field in id_fields):
        return None
    if command == "active_view_start" and (
        isinstance(message["identity_id"], bool)
        or not isinstance(message["identity_id"], int)
        or message["identity_id"] < 0
    ):
        return None
    if command == "active_view_motion_failed":
        reason = message["reason"]
        if (
            not isinstance(reason, str)
            or not reason
            or len(reason) > 128
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for character in reason)
        ):
            return None
    return command


@dataclass(frozen=True)
class D435Sample:
    depth: DepthFrame
    camera: PinholeCamera
    debug_jpeg: bytes
    depth_scale: float


@dataclass(frozen=True)
class ArmPoseSample:
    stamp: FrameStamp
    transform: np.ndarray = field(compare=False)
    joints_deg: np.ndarray = field(compare=False)
    velocities_deg_s: np.ndarray = field(compare=False)
    stationary: bool

    def __post_init__(self) -> None:
        if not isinstance(self.stamp, FrameStamp) or self.stamp.source != "robot_flange_pose":
            raise ValueError("arm sample provenance is invalid")
        transform = np.array(self.transform, dtype=float, copy=True)
        joints = np.array(self.joints_deg, dtype=float, copy=True)
        velocities = np.array(self.velocities_deg_s, dtype=float, copy=True)
        if transform.shape != (4, 4) or not np.isfinite(transform).all():
            raise ValueError("arm transform must be finite")
        if joints.shape != (6,) or not np.isfinite(joints).all():
            raise ValueError("arm joints must contain six finite values")
        if velocities.shape != (6,) or not np.isfinite(velocities).all():
            raise ValueError("arm velocities must contain six finite values")
        if not isinstance(self.stationary, bool):
            raise ValueError("arm stationary state must be explicit")
        transform.setflags(write=False)
        joints.setflags(write=False)
        velocities.setflags(write=False)
        object.__setattr__(self, "transform", transform)
        object.__setattr__(self, "joints_deg", joints)
        object.__setattr__(self, "velocities_deg_s", velocities)


ARM_STATE_KEYS = {
    "type",
    "tcp_position_m",
    "tcp_euler_rad",
    "joints_deg",
    "velocities_deg_s",
    "stationary",
    "monotonic_ns",
}


def _finite_vector(value: Any, length: int, name: str) -> np.ndarray:
    if not isinstance(value, list) or len(value) != length or any(
        isinstance(item, bool) for item in value
    ):
        raise ValueError(f"{name} must contain {length} finite numbers")
    try:
        result = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain {length} finite numbers") from exc
    if not np.isfinite(result).all():
        raise ValueError(f"{name} must contain {length} finite numbers")
    return result


def parse_arm_state(
    command: Any,
    *,
    now_ns: int,
    previous_monotonic_ns: Optional[int] = None,
) -> ArmPoseSample:
    """Validate one sender-timestamped, read-only robot-state sample."""

    if not isinstance(command, dict) or set(command) != ARM_STATE_KEYS:
        raise ValueError("arm state keys are invalid")
    if command.get("type") != "arm_state":
        raise ValueError("arm state type is invalid")
    timestamp_raw = command["monotonic_ns"]
    if (
        not isinstance(timestamp_raw, str)
        or not timestamp_raw.isascii()
        or not timestamp_raw.isdigit()
        or not 1 <= len(timestamp_raw) <= 20
    ):
        raise ValueError("arm state timestamp is invalid")
    timestamp_ns = int(timestamp_raw)
    if timestamp_ns <= 0:
        raise ValueError("arm state timestamp is invalid")
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns <= 0:
        raise ValueError("arm state receipt timestamp is invalid")
    if timestamp_ns > now_ns:
        raise ValueError("arm state timestamp is in the future")
    if now_ns - timestamp_ns > 250_000_000:
        raise ValueError("arm state is stale")
    if previous_monotonic_ns is not None and timestamp_ns <= previous_monotonic_ns:
        raise ValueError("arm state timestamp moved backward")
    stationary = command["stationary"]
    if not isinstance(stationary, bool):
        raise ValueError("arm stationary state must be explicit")
    position = _finite_vector(command["tcp_position_m"], 3, "TCP position")
    euler = _finite_vector(command["tcp_euler_rad"], 3, "TCP Euler")
    joints = _finite_vector(command["joints_deg"], 6, "joints")
    velocities = _finite_vector(command["velocities_deg_s"], 6, "velocities")
    if stationary and np.any(np.abs(velocities) > 0.5):
        raise ValueError("stationary arm state exceeds the velocity threshold")
    return ArmPoseSample(
        stamp=FrameStamp("robot_flange_pose", timestamp_ns, timestamp_ns),
        transform=sdk_pose_transform(position, euler),
        joints_deg=joints,
        velocities_deg_s=velocities,
        stationary=stationary,
    )


def select_online_inputs(
    evidence_guard: Optional[ActiveViewEvidenceGuard],
    arm_sample: Optional[ArmPoseSample],
    *,
    now_ns: int,
) -> tuple[Any, Optional[StampedRobotPose], bool, tuple[str, ...]]:
    """Select trusted calibration/pose inputs for one perception frame."""

    blockers: list[str] = []
    calibration = None
    if evidence_guard is None:
        blockers.append("calibration_unavailable")
    elif not evidence_guard.verify_unchanged():
        blockers.append("calibration_changed")
    else:
        calibration = evidence_guard.evidence.camera
    robot_pose = None
    stationary = False
    if arm_sample is None:
        blockers.append("robot_pose_unavailable")
    elif now_ns < arm_sample.stamp.monotonic_ns or (
        now_ns - arm_sample.stamp.monotonic_ns > 250_000_000
    ):
        blockers.append("robot_pose_stale")
    else:
        robot_pose = StampedRobotPose(arm_sample.stamp, arm_sample.transform)
        stationary = arm_sample.stationary
        if not stationary:
            blockers.append("arm_not_stationary")
    if calibration is None:
        stationary = False
    return calibration, robot_pose, stationary, tuple(blockers)


def expire_active_view_on_evidence_failure(
    coordinator: Optional[ActiveViewSessionCoordinator],
    evidence_guard: Optional[ActiveViewEvidenceGuard],
    blockers: tuple[str, ...],
    *,
    now_ns: int,
) -> tuple[dict[str, Any], ...]:
    """Invalidate one active session when its calibration evidence is no longer trusted."""

    if coordinator is None or coordinator.session is None:
        return ()
    if coordinator.session.phase in {ActiveViewPhase.ABORTED, ActiveViewPhase.COMPLETE}:
        return ()
    if not {"calibration_changed", "calibration_unavailable"}.intersection(blockers):
        return ()
    evidence_id = (
        coordinator.evidence_ids[0]
        if evidence_guard is None
        else evidence_guard.evidence.evidence_id
    )
    return tuple(coordinator.expire_evidence(evidence_id, now_ns=now_ns))


d435_latest: LatestValueBuffer[D435Sample] = LatestValueBuffer()
arm_pose_latest: LatestValueBuffer[ArmPoseSample] = LatestValueBuffer()
active_view_commands = ActiveViewCommandMailbox()
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


def inner_roi_bounds(
    width: int,
    height: int,
    fraction: float,
) -> tuple[int, int, int, int]:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 2
        for value in (width, height)
    ):
        raise ValueError("ROI dimensions must be integers of at least two pixels")
    fraction = float(fraction)
    if not np.isfinite(fraction) or not 0.0 < fraction <= 1.0:
        raise ValueError("ROI fraction must be within (0, 1]")
    margin_x = int(round(width * (1.0 - fraction) / 2.0))
    margin_y = int(round(height * (1.0 - fraction) / 2.0))
    return margin_x, margin_y, width - margin_x - 1, height - margin_y - 1


def _d435_debug_frame(
    frame_bgr: np.ndarray,
    raw_depth: np.ndarray,
    sequence: int,
    inner_roi_fraction: Optional[float] = None,
) -> bytes:
    output = np.array(frame_bgr, copy=True)
    depth_viz = np.clip(raw_depth.astype(np.float32) / 3000.0 * 255.0, 0, 255).astype(
        np.uint8
    )
    depth_viz = cv2.applyColorMap(depth_viz, cv2.COLORMAP_JET)
    depth_viz[raw_depth == 0] = 0
    depth_small = cv2.resize(depth_viz, (160, 120))
    output[-120:, -160:] = depth_small
    if inner_roi_fraction is not None:
        x1, y1, x2, y2 = inner_roi_bounds(
            output.shape[1],
            output.shape[0],
            inner_roi_fraction,
        )
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(
            output,
            f"central depth quality ROI {inner_roi_fraction:.0%}",
            (x1 + 5, max(42, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 220, 255),
            1,
            cv2.LINE_AA,
        )
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


def _capture_d435_once(provenance: FrameStampSequencer) -> None:
    """Own the D435 exactly once and publish aligned depth in metres."""

    pipeline = None
    try:
        import pyrealsense2 as rs

        try:
            inner_roi_fraction = load_active_view_config(
                ACTIVE_VIEW_CONFIG
            ).inner_roi_fraction
        except (OSError, ValueError):
            inner_roi_fraction = None
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
        while not shutdown_flag.is_set():
            frames = align.process(pipeline.wait_for_frames(timeout_ms=1000))
            color = frames.get_color_frame()
            depth = frames.get_depth_frame()
            if not color or not depth:
                continue
            monotonic_ns = time.monotonic_ns()
            stamp = provenance.next_stamp(monotonic_ns)
            frame_bgr = np.array(np.asanyarray(color.get_data()), copy=True)
            raw_depth = np.array(np.asanyarray(depth.get_data()), dtype=np.uint16, copy=True)
            depth_m = depth_to_metres(raw_depth, depth_scale)
            debug_jpeg = _d435_debug_frame(
                frame_bgr,
                raw_depth,
                stamp.frame_id,
                inner_roi_fraction,
            )
            sample = D435Sample(
                depth=DepthFrame(
                    stamp, depth_m
                ),
                camera=camera,
                debug_jpeg=debug_jpeg,
                depth_scale=depth_scale,
            )
            sequence = d435_latest.publish(sample)
            _update_state(d435_sequence=sequence)
            _write_mjpeg(sys.stdout.buffer, debug_jpeg, _d435_output_lock)
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


def capture_d435(retry_initial_s: float = 0.5) -> None:
    """Retry transient USB/UVC startup failures without growing a frame queue."""

    backoff_s = max(0.0, float(retry_initial_s))
    provenance = FrameStampSequencer("d435_depth")
    while not shutdown_flag.is_set():
        _capture_d435_once(provenance)
        if shutdown_flag.is_set():
            return
        emit(
            "camera_status",
            d435_ready=False,
            retrying=True,
            retry_after_s=backoff_s,
        )
        if shutdown_flag.wait(backoff_s):
            return
        backoff_s = min(2.0, max(0.1, backoff_s * 2.0))


def _load_online_engine():
    config = load_online_vision_config(VISION_CONFIG)
    active_view_config = load_active_view_config(ACTIVE_VIEW_CONFIG)
    evidence_guard = None
    evidence_error = None
    try:
        evidence_guard = ActiveViewEvidenceGuard.load(
            ACTIVE_VIEW_CAMERA_EVIDENCE,
            ACTIVE_VIEW_TABLE_EVIDENCE,
            ACTIVE_VIEW_CATALOG,
            evidence_dir=ACTIVE_VIEW_EVIDENCE_DIR,
        )
        active_view_config = replace(
            active_view_config,
            table_plane=evidence_guard.evidence.table,
            observation_poses=evidence_guard.evidence.poses,
        )
    except (ActiveViewEvidenceError, OSError, ValueError) as error:
        evidence_error = str(error)[:512]
    emit(
        "vision_status",
        online=False,
        phase="loading_models",
        canonical_rgb_source=config.roles.canonical_rgb_source,
        metric_depth_source=config.roles.metric_depth_source,
        task_checkpoint_validated=config.task_checkpoint_validated,
        active_view_execution_enabled=False,
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
    active_view = ActiveViewDryRunAdapter(active_view_config)
    return config, OnlinePerceptionEngine(
        segmenter,
        encoder,
        perception,
        config,
        active_view=active_view,
    ), active_view_config, evidence_guard, evidence_error


def run_online_perception() -> None:
    """Read newest Lumos frame, pair newest D435 depth, and emit read-only output."""

    try:
        config, engine, active_view_config, evidence_guard, evidence_error = _load_online_engine()
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
    coordinator = None
    if evidence_guard is not None:
        coordinator = ActiveViewSessionCoordinator(
            active_view_config,
            evidence_ids=(
                evidence_guard.evidence.evidence_id,
                evidence_guard.evidence.camera.calibration.calibration_id,
            ),
        )
    last_lumos_sequence = -1
    last_d435_sequence = 0
    backoff_s = 0.1
    while not shutdown_flag.is_set():
        try:
            for command in active_view_commands.drain():
                if coordinator is None:
                    emit_event(
                        {
                            "type": "active_view_protocol_rejected",
                            "reason": "active_view_evidence_unavailable",
                            "session_id": command.get("session_id"),
                            "robot_execution_enabled": False,
                            "active_view_execution_enabled": False,
                        }
                    )
                    continue
                for active_event in coordinator.handle_command(
                    command,
                    now_ns=time.monotonic_ns(),
                ):
                    emit_event(active_event)
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
            arm = None if arm_item is None else arm_item[1]
            calibration, robot_pose, arm_stationary, input_blockers = select_online_inputs(
                evidence_guard,
                arm,
                now_ns=now_ns,
            )
            for active_event in expire_active_view_on_evidence_failure(
                coordinator,
                evidence_guard,
                input_blockers,
                now_ns=now_ns,
            ):
                emit_event(active_event)
            result = engine.process(
                pair,
                robot_pose=robot_pose,
                calibration=calibration,
                arm_stationary=arm_stationary,
                now_ns=now_ns,
                current_joints_deg=(
                    None
                    if arm is None or robot_pose is None or not arm_stationary
                    else arm.joints_deg
                ),
            )
            if (
                coordinator is not None
                and coordinator.session is not None
                and coordinator.session.phase
                in {ActiveViewPhase.TARGET_LOCKED, ActiveViewPhase.REFINE_VIEW}
            ):
                matching = next(
                    (
                        proposal
                        for proposal in result.active_view_proposals
                        if proposal.identity_id == coordinator.session.identity_id
                    ),
                    None,
                )
                if matching is not None:
                    for active_event in coordinator.offer_proposal(
                        matching,
                        now_ns=now_ns,
                    ):
                        emit_event(active_event)
            event = result.to_event()
            emit_event(event)
            blockers = list(result.blockers)
            blockers.extend(input_blockers)
            if evidence_error and evidence_guard is None:
                blockers.append("calibration_unavailable")
            blockers = list(dict.fromkeys(blockers))
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
    now_ns = time.monotonic_ns()
    previous = _state_snapshot().get("robot_pose_monotonic_ns")
    try:
        sample = parse_arm_state(
            command,
            now_ns=now_ns,
            previous_monotonic_ns=previous,
        )
    except ValueError:
        return
    sequence = arm_pose_latest.publish(sample)
    _update_state(
        robot_pose_sequence=sequence,
        robot_pose_monotonic_ns=sample.stamp.monotonic_ns,
        arm_stationary=sample.stationary,
    )


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
        active_view_execution_enabled=False,
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
        elif command_type in SESSION_COMMAND_KEYS:
            active_view_commands.publish(command)
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
