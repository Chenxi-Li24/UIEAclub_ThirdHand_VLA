#!/usr/bin/env python3
"""XVisio capture and optional bottle inference process for Vision Service."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[3]
DRIVER_SRC = ROOT / "drivers/xvisio/src"
if str(DRIVER_SRC) not in sys.path:
    sys.path.insert(0, str(DRIVER_SRC))


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
                result = model.infer(frame.rgb)
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

    def select(self, stable_id: int | None) -> None:
        if stable_id is not None and not 1 <= stable_id <= 5:
            raise ValueError("stable_id must be within [1, 5]")
        with self._condition:
            self._selected_id = stable_id
        self._publish_status()

    def selected_id(self) -> int | None:
        with self._condition:
            return self._selected_id

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "camera": dict(self._camera),
                "inference": dict(self._inference),
                "selection": {"stableId": self._selected_id},
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
    return parser


def run_bridge(args: argparse.Namespace) -> int:
    import yaml

    config_data = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    serial = str(config_data["camera_serial"])
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

    from xvisio_stream import XVisioStream

    stream = XVisioStream(args.executable, expected_serial=serial)

    def frames():
        sequence = 0
        stream.start()
        while not stop.is_set():
            frame = stream.read_after(sequence, timeout_s=1.0)
            if frame is None:
                continue
            sequence = frame.sequence
            yield frame

    def model_factory():
        from thirdhand_va.common.config import VisionConfig
        from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend

        config = VisionConfig.from_yaml(args.config)
        backend = GroundedSamBackend(config, local_files_only=True)
        backend._load_models()
        return backend

    runtime_ref: dict[str, CameraRuntime] = {}

    def on_raw(frame) -> None:
        raw_stream.write(mjpeg_part(
            encode_rgb_jpeg(frame.rgb, quality),
            sequence=frame.sequence,
        ))
        depth_stream.write(mjpeg_part(
            encode_depth_jpeg(
                frame.depth_m,
                float(config_data["min_depth_m"]),
                float(config_data["max_depth_m"]),
            ),
            sequence=frame.sequence,
        ))

    def on_inference(frame, candidates) -> None:
        runtime = runtime_ref["runtime"]
        overlay, targets = render_detection_overlay(
            frame.rgb,
            candidates,
            runtime.selected_id(),
        )
        import cv2
        ok, encoded = cv2.imencode(
            ".jpg",
            overlay,
            [cv2.IMWRITE_JPEG_QUALITY, quality],
        )
        if not ok:
            raise RuntimeError("overlay JPEG encoding failed")
        vision_stream.write(mjpeg_part(
            encoded.tobytes(),
            sequence=frame.sequence,
        ))
        events.write({
            "type": "detection_result",
            "sequence": int(frame.sequence),
            "targets": targets,
            "selectedStableId": runtime.selected_id(),
        })

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
                    runtime.select(int(message["stableId"]))
                elif message.get("type") == "release_target":
                    runtime.select(None)
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
        "type": "bridge_started",
        "cameraSerial": serial,
        "robotControlEnabled": False,
    })
    try:
        while not stop.wait(0.25):
            pass
    finally:
        runtime.close()
        stream.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_bridge(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
