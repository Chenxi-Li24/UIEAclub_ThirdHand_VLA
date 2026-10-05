#!/usr/bin/env python3
"""XVisio capture and optional bottle inference process for Vision Service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable


ROOT = Path(os.environ.get(
    "THIRDHAND_LIVE_ROOT", Path.home() / "ThirdHand" / "UIEAclub_ThirdHand_VLA"
)).resolve()
sys.path.insert(0, str(ROOT / "services/vision/python"))
DRIVER_SRC = ROOT / "drivers/xvisio/src"
if str(DRIVER_SRC) not in sys.path:
    sys.path.insert(0, str(DRIVER_SRC))


class StreamDemand:
    """Thread-safe demand state for browser-visible MJPEG streams."""

    KINDS = frozenset({"raw", "vision", "depth"})

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = {kind: False for kind in self.KINDS}

    def set_enabled(self, kind: str, enabled: bool) -> None:
        if kind not in self.KINDS or not isinstance(enabled, bool):
            raise ValueError("invalid stream demand")
        with self._lock:
            self._enabled[kind] = enabled

    def requested(self, kind: str) -> bool:
        if kind not in self.KINDS:
            return False
        with self._lock:
            return self._enabled[kind]


def write_selected_target_snapshot(
    frame,
    decision,
    *,
    request_id: str,
    output_dir: str | Path,
    observed_at_ms: int,
) -> dict[str, Any]:
    """Persist one validated selected target from a single aligned RGB-D frame."""

    import numpy as np

    result = {
        "type": "selected_target_export_result",
        "requestId": request_id,
        "ok": False,
    }
    selected_id = decision.selected_stable_id
    track = next(
        (item for item in decision.tracks if item.stable_id == selected_id),
        None,
    )
    if selected_id is None or track is None:
        return {**result, "code": "selected_target_missing"}
    if track.state in {"lost", "retired", "occluded"}:
        return {**result, "code": "selected_target_lost"}
    if not track.depth_supported:
        return {**result, "code": "selected_target_depth_invalid"}

    mask = np.asarray(track.candidate.mask, dtype=np.bool_)
    if mask.shape != frame.depth_m.shape or not mask.any():
        return {**result, "code": "selected_target_mask_invalid"}
    valid = (
        mask
        & np.isfinite(frame.depth_m)
        & np.isfinite(frame.xyz_camera_m).all(axis=2)
    )
    if not valid.any():
        return {**result, "code": "selected_target_depth_invalid"}

    metadata = {
        "schema": "thirdhand-selected-target-bundle-v1",
        "request_id": request_id,
        "selected_stable_id": int(selected_id),
        "frame_id": int(frame.sequence),
        "monotonic_ns": int(frame.monotonic_ns),
        "observed_at_ms": int(observed_at_ms),
        "camera_serial": str(frame.camera_serial),
        "point_frame": "xvisio_color",
        "length_unit": "m",
        "bbox_xyxy": [float(value) for value in track.candidate.bbox_xyxy],
        "track_state": str(track.state),
        "depth_valid": True,
        "status": str(decision.status),
        "blockers": list(track.blockers),
    }
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target,
            prefix="selected-target-",
            suffix=".npz",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(
                stream,
                rgb=np.asarray(frame.rgb, dtype=np.uint8),
                depth_m=np.asarray(frame.depth_m, dtype=np.float32),
                xyz_camera_m=np.asarray(frame.xyz_camera_m, dtype=np.float32),
                mask=mask,
                metadata_json=np.asarray(
                    json.dumps(metadata, ensure_ascii=True, sort_keys=True)
                ),
            )
        return {
            **result,
            "ok": True,
            "path": str(temporary),
            "schema": metadata["schema"],
            "frame_id": metadata["frame_id"],
            "length_unit": metadata["length_unit"],
            "point_frame": metadata["point_frame"],
        }
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def write_raw_frame_snapshot(
    frame, *, request_id: str, output_dir: str | Path, observed_at_ms: int,
) -> dict[str, Any]:
    """Persist one complete aligned RGB-D frame without changing vision state."""
    import numpy as np

    metadata = {
        "schema": "thirdhand-raw-rgbd-frame-v1",
        "request_id": request_id,
        "frame_id": int(frame.sequence),
        "monotonic_ns": int(frame.monotonic_ns),
        "observed_at_ms": int(observed_at_ms),
        "camera_serial": str(frame.camera_serial),
        "point_frame": "xvisio_color",
        "length_unit": "m",
    }
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target, prefix="raw-rgbd-", suffix=".npz", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            np.savez_compressed(
                stream,
                rgb=np.asarray(frame.rgb, dtype=np.uint8),
                depth_m=np.asarray(frame.depth_m, dtype=np.float32),
                xyz_camera_m=np.asarray(frame.xyz_camera_m, dtype=np.float32),
                metadata_json=np.asarray(json.dumps(metadata, ensure_ascii=True, sort_keys=True)),
            )
        return {
            "type": "raw_frame_export_result", "requestId": request_id,
            "ok": True, "path": str(temporary), "schema": metadata["schema"],
            "frame_id": metadata["frame_id"], "length_unit": "m",
            "point_frame": "xvisio_color",
        }
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


class CameraRuntime:
    """Run capture and inference independently around a one-slot frame mailbox."""

    def __init__(
        self,
        frames: Iterable[Any],
        *,
        model_factory: Callable[[], Any],
        on_raw: Callable[[Any], None] | None = None,
        on_inference: Callable[[Any, Any], None] | None = None,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self._frames = iter(frames)
        self._model_factory = model_factory
        self._on_raw = on_raw
        self._on_inference = on_inference
        self._on_status = on_status
        self._stop = stop_event or threading.Event()
        self._condition = threading.Condition()
        self._latest = None
        self._capture_done = False
        self._camera = {"status": "starting", "sequence": None, "error": None}
        self._inference = {"status": "loading", "error": None}
        self._selected_id: int | None = None
        self._selection_request_id: str | None = None
        self._model = None
        self._model_lock = threading.Lock()
        self._capture_thread: threading.Thread | None = None
        self._inference_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._capture_thread is not None:
            raise RuntimeError("camera runtime is already started")
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name="xvisio-capture",
            daemon=True,
        )
        self._inference_thread = threading.Thread(
            target=self._inference_loop,
            name="xvisio-inference",
            daemon=True,
        )
        self._capture_thread.start()
        self._inference_thread.start()

    def _capture_loop(self) -> None:
        try:
            for frame in self._frames:
                if self._stop.is_set():
                    break
                with self._condition:
                    self._latest = frame
                    self._camera = {
                        "status": "ready",
                        "sequence": int(frame.sequence),
                        "error": None,
                    }
                    self._condition.notify_all()
                if self._on_raw is not None:
                    try:
                        self._on_raw(frame)
                    except Exception as error:
                        self._notify_error("raw preview", error)
                self._publish_status()
        except BaseException as error:
            with self._condition:
                self._camera = {
                    "status": "error",
                    "sequence": self._camera["sequence"],
                    "error": str(error),
                }
                self._condition.notify_all()
            self._publish_status()
        finally:
            with self._condition:
                self._capture_done = True
                self._condition.notify_all()

    def _inference_loop(self) -> None:
        try:
            model = self._model_factory()
            with self._condition:
                self._model = model
                self._inference = {"status": "ready", "error": None}
            self._publish_status()
        except BaseException as error:
            with self._condition:
                self._inference = {"status": "error", "error": str(error)}
            self._publish_status()
            return

        sequence = -1
        while not self._stop.is_set():
            with self._condition:
                self._condition.wait_for(
                    lambda: self._stop.is_set()
                    or self._capture_done
                    or (
                        self._latest is not None
                        and int(self._latest.sequence) > sequence
                    ),
                    timeout=0.5,
                )
                if self._stop.is_set():
                    return
                if self._latest is None or int(self._latest.sequence) <= sequence:
                    if self._capture_done:
                        return
                    continue
                frame = self._latest
            sequence = int(frame.sequence)
            try:
                with self._model_lock:
                    process_frame = getattr(model, "process_frame", None)
                    result = (
                        process_frame(frame)
                        if callable(process_frame)
                        else model.infer(frame.rgb)
                    )
                if self._on_inference is not None:
                    self._on_inference(frame, result)
            except BaseException as error:
                with self._condition:
                    self._inference = {"status": "error", "error": str(error)}
                self._publish_status()
                return

    def _notify_error(self, stage: str, error: BaseException) -> None:
        if self._on_status is not None:
            self._on_status({
                "type": "vision_warning",
                "stage": stage,
                "error": str(error),
            })

    def _publish_status(self) -> None:
        if self._on_status is not None:
            self._on_status({"type": "runtime_status", **self.status()})

    def next_raw_frame(self, timeout: float) -> Any | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._latest is not None
                or self._camera["status"] == "error",
                timeout=max(0.0, float(timeout)),
            )
            return self._latest

    def select(
        self,
        stable_id: int | None,
        request_id: str | None = None,
    ) -> bool:
        if stable_id is not None and not 1 <= stable_id <= 5:
            raise ValueError("stable_id must be within [1, 5]")
        with self._condition:
            model = self._model
            current_request_id = self._selection_request_id
        if model is None:
            return False
        accepted = True
        with self._model_lock:
            if stable_id is None:
                release = getattr(model, "release_target", None)
                if callable(release) and current_request_id is not None:
                    accepted = bool(release(request_id or current_request_id))
            else:
                select = getattr(model, "select_target", None)
                accepted = not callable(select) or bool(
                    select(stable_id, request_id or f"vision-{time.monotonic_ns()}")
                )
        if not accepted:
            return False
        with self._condition:
            self._selected_id = stable_id
            self._selection_request_id = None if stable_id is None else request_id
        self._publish_status()
        return True

    def selected_id(self) -> int | None:
        with self._condition:
            return self._selected_id

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "camera": dict(self._camera),
                "inference": dict(self._inference),
                "selection": {
                    "stableId": self._selected_id,
                    "requestId": self._selection_request_id,
                },
            }

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        for thread in (self._capture_thread, self._inference_thread):
            if thread is not None:
                thread.join(timeout=2.0)


class EventWriter:
    def __init__(self, stream) -> None:
        self.stream = stream
        self.lock = threading.Lock()

    def write(self, message: dict[str, Any]) -> None:
        data = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            .encode("utf-8") + b"\n"
        )
        with self.lock:
            self.stream.write(data)
            self.stream.flush()


class UnifiedVisionRuntime:
    """Adapt one validated XVisio frame to the shared PinZi vision pipeline."""

    def __init__(self, config, backend, projection=None) -> None:
        from pipeline_with_quality import VisionPipeline

        self.config = config
        self.projection = projection
        self.pipeline = VisionPipeline(config, backend)

    def process_frame(self, frame):
        from thirdhand_va.common.contracts import RgbdFrame

        base_transform = None
        if self.projection is not None and self.projection.projection_allowed:
            base_transform = self.projection.for_frame(int(frame.monotonic_ns))
        return self.pipeline.process(
            RgbdFrame(
                sequence=int(frame.sequence),
                monotonic_ns=int(frame.monotonic_ns),
                camera_serial=str(frame.camera_serial),
                rgb=frame.rgb,
                depth_m=frame.depth_m,
                xyz_camera_m=frame.xyz_camera_m,
            ),
            now_ns=int(frame.monotonic_ns),
            t_base_camera=base_transform,
        )

    def select_target(self, stable_id: int, request_id: str) -> bool:
        return self.pipeline.select(stable_id, request_id)

    def release_target(self, request_id: str) -> bool:
        selection = self.pipeline.selection
        if selection is not None and selection.request_id != request_id:
            return False
        self.pipeline.release(request_id)
        return True


def model_provenance(config) -> dict[str, str]:
    return {
        "vision_config_id": config.content_id,
        "camera_registration_id": config.camera_registration_id,
        "camera_mount_id": config.camera_mount_id,
        "grounding_model": config.grounding_model,
        "grounding_revision": config.grounding_revision,
        "grounding_weights_sha256": config.grounding_weights_sha256,
        "sam_model": config.sam_model,
        "sam_revision": config.sam_revision,
        "sam_weights_sha256": config.sam_weights_sha256,
    }


def attach_depth_evidence(event, decision, frame, config, projection=None) -> None:
    """Attach metric depth and fail-closed base projection when approved."""

    import numpy as np
    from handeye_projection import project_point
    from geometry_quality.pointcloud import robust_mask_points

    base_transform = None
    base_status = "handeye_not_configured"
    if projection is not None:
        if not projection.projection_allowed:
            base_status = "physical_validation_pending"
        else:
            base_transform = projection.for_frame(int(frame.monotonic_ns))
            base_status = "ready" if base_transform is not None else (
                projection.last_rejection or "robot_state_unavailable"
            )

    tracks = {track.candidate.detection_id: track for track in decision.tracks}
    for target in event.get("targets", []):
        track = tracks.get(target.get("detection_id"))
        if track is None:
            continue
        mask = np.asarray(track.candidate.mask, dtype=bool)
        if mask.shape != frame.depth_m.shape:
            continue
        valid = (
            mask
            & np.isfinite(frame.depth_m)
            & (frame.depth_m >= config.min_depth_m)
            & (frame.depth_m <= config.max_depth_m)
            & np.isfinite(frame.xyz_camera_m).all(axis=2)
        )
        mask_pixels = int(mask.sum())
        raw_valid_points = int(valid.sum())
        points, _ = robust_mask_points(
            frame.xyz_camera_m, valid,
            min_depth_m=config.min_depth_m,
            max_depth_m=config.max_depth_m, mad_scale=3.5,
        )
        valid_points = len(points)
        ratio = 0.0 if mask_pixels == 0 else valid_points / mask_pixels
        target.update({
            "stableId": target.get("stable_id"),
            "depth_valid_ratio": float(ratio),
            "valid_depth_points": valid_points,
            "raw_valid_depth_points": raw_valid_points,
            "raw_depth_valid_ratio": 0.0 if mask_pixels == 0 else raw_valid_points / mask_pixels,
            "camera_xyz_m": None,
            "base_xyz_m": None,
            "position_std_m": None,
            "depth_m": None,
            "base_pose_status": base_status,
        })
        if track.state in {"occluded", "lost", "retired"}:
            target["depth_valid"] = False
            target["depth_valid_ratio"] = 0.0
            target["valid_depth_points"] = 0
            target["camera_xyz_m"] = None
            target["position_std_m"] = None
            target["depth_m"] = None
            target["blockers"] = list(dict.fromkeys(
                [*target.get("blockers", []), f"target_{track.state}"]
            ))
            continue
        if valid_points < config.min_depth_points or ratio < config.min_depth_ratio:
            target["depth_valid"] = False
            target["blockers"] = list(dict.fromkeys(
                [*target.get("blockers", []), "insufficient_filtered_depth"]
            ))
            continue
        if valid_points:
            center = np.median(points, axis=0)
            spread = np.std(points, axis=0)
            target["camera_xyz_m"] = [float(value) for value in center]
            if base_transform is not None:
                target["base_xyz_m"] = [
                    float(value) for value in project_point(base_transform, center)
                ]
            target["position_std_m"] = [float(value) for value in spread]
            target["depth_m"] = float(center[2])
    event["selectedStableId"] = event.get("selected_stable_id")


def mjpeg_part(jpeg: bytes, *, sequence: int) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(jpeg)}\r\n".encode("ascii")
        + f"X-ThirdHand-Sequence: {sequence}\r\n\r\n".encode("ascii")
        + jpeg
        + b"\r\n"
    )


def encode_rgb_jpeg(rgb, quality: int) -> bytes:
    import cv2
    import numpy as np

    bgr = np.asarray(rgb, dtype=np.uint8)[..., ::-1]
    ok, encoded = cv2.imencode(
        ".jpg",
        bgr,
        [cv2.IMWRITE_JPEG_QUALITY, quality],
    )
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return encoded.tobytes()


def encode_depth_jpeg(depth_m, min_depth_m: float, max_depth_m: float) -> bytes:
    import cv2
    import numpy as np

    depth = np.asarray(depth_m, dtype=np.float32)
    valid = np.isfinite(depth) & (depth >= min_depth_m) & (depth <= max_depth_m)
    normalized = np.zeros(depth.shape, dtype=np.uint8)
    normalized[valid] = np.clip(
        (max_depth_m - depth[valid]) * 255 / (max_depth_m - min_depth_m),
        0,
        255,
    ).astype(np.uint8)
    heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_TURBO)
    heatmap[~valid] = 0
    ok, encoded = cv2.imencode(".jpg", heatmap)
    if not ok:
        raise RuntimeError("depth JPEG encoding failed")
    return encoded.tobytes()


def render_detection_overlay(rgb, candidates, selected_id: int | None):
    import cv2
    import numpy as np

    image = np.asarray(rgb, dtype=np.uint8)[..., ::-1].copy()
    rows = sorted(
        list(candidates)[:5],
        key=lambda item: (item.bbox_xyxy[0] + item.bbox_xyxy[2]) / 2,
    )
    used_ids: set[int] = set()
    targets = []
    for fallback_id, candidate in enumerate(rows, start=1):
        tracker_id = int(getattr(candidate, "detection_id", fallback_id - 1)) + 1
        stable_id = tracker_id if 1 <= tracker_id <= 5 else fallback_id
        if stable_id in used_ids:
            stable_id = next(value for value in range(1, 6) if value not in used_ids)
        used_ids.add(stable_id)
        x0, y0, x1, y1 = [
            int(round(value)) for value in candidate.bbox_xyxy
        ]
        selected = stable_id == selected_id
        color = (60, 220, 80) if selected else (30, 180, 255)
        mask = getattr(candidate, "mask", None)
        if mask is not None and getattr(mask, "shape", None) == image.shape[:2]:
            tint = np.zeros_like(image)
            tint[mask] = color
            image = cv2.addWeighted(image, 1.0, tint, 0.2, 0.0)
        cv2.rectangle(image, (x0, y0), (x1, y1), color, 4 if selected else 2)
        label = f"{stable_id} SELECTED" if selected else str(stable_id)
        cv2.putText(
            image,
            label,
            (x0, max(18, y0 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )
        targets.append({
            "stableId": stable_id,
            "label": str(getattr(candidate, "prompt_label", "bottle")),
            "score": float(getattr(candidate, "score", 0.0)),
            "bbox": [x0, y0, x1, y1],
            "selected": selected,
        })
    return image, targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs/vision.yaml",
    )
    parser.add_argument(
        "--executable",
        type=Path,
        default=ROOT / "runtime/build/xvisio/xvisio_rgbd_stream",
    )
    parser.add_argument("--handeye", type=Path, default=None)
    parser.add_argument(
        "--urdf",
        type=Path,
        default=None,
    )
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    import yaml

    config_data = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    from thirdhand_va.common.config import VisionConfig

    vision_config = VisionConfig.from_yaml(args.config)
    serial = str(config_data["camera_serial"])
    projection = None
    if args.handeye is not None:
        if args.urdf is None:
            raise ValueError("handeye_requires_robot_urdf")
        from handeye_projection_with_frames import HandEyeProjection

        projection = HandEyeProjection(
            args.handeye,
            serial,
            vision_config.camera_registration_id,
            vision_config.camera_mount_id,
            args.urdf,
            allow_numerical_only=(
                os.environ.get("THIRDHAND_ALLOW_NUMERICAL_HANDEYE") == "1"
            ),
        )
    quality = int(os.environ.get("CAMERA_JPEG_QUALITY", "75"))
    event_stream = os.fdopen(
        int(os.environ.get("CAMERA_EVENT_FD", "3")),
        "wb",
        buffering=0,
        closefd=False,
    )
    raw_stream = os.fdopen(
        int(os.environ.get("XVISIO_RAW_FD", "4")),
        "wb",
        buffering=0,
        closefd=False,
    )
    vision_stream = os.fdopen(
        int(os.environ.get("VISION_OVERLAY_FD", "5")),
        "wb",
        buffering=0,
        closefd=False,
    )
    depth_stream = os.fdopen(
        int(os.environ.get("DEPTH_HEATMAP_FD", "6")),
        "wb",
        buffering=0,
        closefd=False,
    )
    events = EventWriter(event_stream)
    stop = threading.Event()
    stream_demand = StreamDemand()

    from xvisio_stream import XVisioStream

    stream = XVisioStream(args.executable, expected_serial=serial)

    def frames():
        first_frame_timeout = max(
            1.0, float(os.environ.get("XVISIO_FIRST_FRAME_TIMEOUT_SEC", "15"))
        )
        frame_timeout = max(
            1.0, float(os.environ.get("XVISIO_FRAME_TIMEOUT_SEC", "10"))
        )
        sequence = 0
        last_frame_at = time.monotonic()
        stream.start()
        while not stop.is_set():
            frame = stream.read_after(sequence, timeout_s=1.0)
            if frame is None:
                timeout = first_frame_timeout if sequence == 0 else frame_timeout
                if time.monotonic() - last_frame_at >= timeout:
                    stage = "first frame" if sequence == 0 else "next frame"
                    raise RuntimeError(
                        f"XVisio {stage} timeout after {timeout:.1f}s"
                    )
                continue
            sequence = frame.sequence
            last_frame_at = time.monotonic()
            yield frame

    def model_factory():
        from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend

        backend = GroundedSamBackend(vision_config, local_files_only=True)
        backend._load_models()
        return UnifiedVisionRuntime(vision_config, backend, projection=projection)

    runtime_ref: dict[str, CameraRuntime] = {}
    export_dir = Path(os.environ.get(
        "SELECTED_TARGET_EXPORT_DIR",
        ROOT / "runtime/vision/selected-target-exports",
    ))
    export_lock = threading.Lock()
    pending_export: dict[str, str] = {}
    pending_raw_export: dict[str, str] = {}

    def on_raw(frame) -> None:
        if stream_demand.requested("raw"):
            raw_stream.write(mjpeg_part(
                encode_rgb_jpeg(frame.rgb, quality),
                sequence=frame.sequence,
            ))
        if stream_demand.requested("depth"):
            depth_stream.write(mjpeg_part(
                encode_depth_jpeg(
                    frame.depth_m,
                    float(config_data["min_depth_m"]),
                    float(config_data["max_depth_m"]),
                ),
                sequence=frame.sequence,
            ))
        with export_lock:
            request_id = pending_raw_export.pop("requestId", None)
        if request_id is not None:
            try:
                result = write_raw_frame_snapshot(
                    frame, request_id=request_id, output_dir=export_dir,
                    observed_at_ms=int(time.time_ns() // 1_000_000),
                )
            except BaseException as error:
                result = {
                    "type": "raw_frame_export_result", "requestId": request_id,
                    "ok": False, "code": "raw_frame_export_failed", "message": str(error),
                }
            events.write(result)

    render_state = {"last_ns": None}

    def on_inference(frame, decision) -> None:
        from thirdhand_va.vision.adapters.event_publisher import build_detection_event
        from thirdhand_va.vision.adapters.mjpeg_publisher import FrameProvenance
        from thirdhand_va.vision.visualization.overlay import (
            RenderMetrics,
            encode_jpeg,
            render_overlay,
        )

        now_ns = time.monotonic_ns()
        previous_ns = render_state["last_ns"]
        render_state["last_ns"] = now_ns
        fps = 0.0 if previous_ns is None else 1_000_000_000 / max(1, now_ns - previous_ns)
        latency_ms = max(0.0, (now_ns - int(frame.monotonic_ns)) / 1_000_000)
        rendered = render_overlay(
            frame.rgb,
            decision,
            RenderMetrics(fps=fps, latency_ms=latency_ms),
        )
        encoded = encode_jpeg(rendered.image, quality=quality)
        if stream_demand.requested("vision"):
            vision_stream.write(mjpeg_part(
                encoded,
                sequence=frame.sequence,
            ))
        provenance = FrameProvenance(
            frame_id=int(frame.sequence),
            monotonic_ns=int(frame.monotonic_ns),
            observed_at_ms=int(time.time_ns() // 1_000_000),
        )
        event = build_detection_event(
            decision,
            provenance,
            encoded,
            model_provenance=model_provenance(vision_config),
        )
        attach_depth_evidence(event, decision, frame, vision_config, projection)
        events.write(event)
        with export_lock:
            request_id = pending_export.pop("requestId", None)
        if request_id is not None:
            try:
                export_result = write_selected_target_snapshot(
                    frame,
                    decision,
                    request_id=request_id,
                    output_dir=export_dir,
                    observed_at_ms=provenance.observed_at_ms,
                )
            except BaseException as error:
                export_result = {
                    "type": "selected_target_export_result",
                    "requestId": request_id,
                    "ok": False,
                    "code": "selected_target_export_failed",
                    "message": str(error),
                }
            events.write(export_result)

    runtime = CameraRuntime(
        frames(),
        model_factory=model_factory,
        on_raw=on_raw,
        on_inference=on_inference,
        on_status=events.write,
        stop_event=stop,
    )
    runtime_ref["runtime"] = runtime

    def consume_commands() -> None:
        for line in sys.stdin:
            if stop.is_set():
                return
            try:
                message = json.loads(line)
                if message.get("type") == "select_target":
                    request_id = str(
                        message.get("requestId") or f"vision-{time.monotonic_ns()}"
                    )
                    stable_id = int(message["stableId"])
                    accepted = runtime.select(stable_id, request_id)
                    events.write({
                        "type": "selection_result",
                        "accepted": accepted,
                        "stableId": stable_id,
                        "requestId": request_id,
                        "reason": None if accepted else "target_not_confirmed",
                    })
                elif message.get("type") == "release_target":
                    request_id = message.get("requestId")
                    accepted = runtime.select(
                        None,
                        None if request_id is None else str(request_id),
                    )
                    events.write({
                        "type": "release_result",
                        "accepted": accepted,
                        "requestId": request_id,
                    })
                elif message.get("type") == "set_stream_enabled":
                    stream_demand.set_enabled(
                        str(message["kind"]),
                        bool(message["enabled"]),
                    )
                elif message.get("type") == "export_selected_target":
                    request_id = str(message["requestId"])
                    if not request_id:
                        raise ValueError("missing export request id")
                    with export_lock:
                        if "requestId" in pending_export:
                            events.write({
                                "type": "selected_target_export_result",
                                "requestId": request_id,
                                "ok": False,
                                "code": "export_in_progress",
                            })
                        else:
                            pending_export["requestId"] = request_id
                elif message.get("type") == "export_raw_frame":
                    request_id = str(message["requestId"])
                    with export_lock:
                        if "requestId" in pending_raw_export:
                            events.write({
                                "type": "raw_frame_export_result", "requestId": request_id,
                                "ok": False, "code": "export_in_progress",
                            })
                        else:
                            pending_raw_export["requestId"] = request_id
                elif message.get("type") == "arm_state" and projection is not None:
                    projection.update(message, time.monotonic_ns())
                elif message.get("type") == "shutdown":
                    stop.set()
                    return
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue

    command_thread = threading.Thread(
        target=consume_commands,
        name="vision-commands",
        daemon=True,
    )
    command_thread.start()

    def request_stop(_signum, _frame) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    runtime.start()
    events.write({
        "type": "bridge_ready",
        "camera_serial": serial,
        "registration_id": vision_config.camera_registration_id,
        "camera_mount_id": vision_config.camera_mount_id,
        "vision_config_id": vision_config.content_id,
        "calibration_id": projection.calibration_id if projection is not None else None,
        "calibration_approved": (
            projection.physically_validated if projection is not None else False
        ),
        "calibration_projection_enabled": (
            projection.projection_allowed if projection is not None else False
        ),
        "model_provenance": model_provenance(vision_config),
        "robotControlEnabled": False,
    })
    exit_code = 0
    try:
        while not stop.wait(0.25):
            camera_status = runtime.status()["camera"]
            if camera_status["status"] == "error":
                events.write({
                    "type": "bridge_fatal",
                    "stage": "camera",
                    "error": camera_status["error"],
                })
                exit_code = 1
                break
    finally:
        runtime.close()
        stream.close()
    return exit_code


def main(argv: list[str] | None = None) -> int:
    return run_bridge(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
