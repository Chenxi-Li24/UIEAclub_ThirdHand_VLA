#!/usr/bin/env python3
"""Compose reusable V and A modules into the bottle-picking camera bridge."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
from typing import BinaryIO, Iterable, Iterator

from thirdhand_va.vision.adapters import (
    FrameProvenance,
    LatestFramePublisher,
    build_mjpeg_part,
)
from thirdhand_va.vision.camera.recording import read_frame_bundle
from thirdhand_va.vision.camera.stream import XVisioStream
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame, VisionDecision
from thirdhand_va.action.calibration import (
    ArmStateStore,
    HandEyeCalibration,
    build_base_grasp_preview,
    rpy_xyz_transform,
)
from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend
from thirdhand_va.vision.pipeline import VisionPipeline
from thirdhand_va.vision.visualization import (
    RenderMetrics,
    encode_jpeg,
    render_depth_heatmap,
    render_overlay,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=("live", "replay"),
        default=os.environ.get("THIRDHAND_VA_SOURCE", "live"),
    )
    parser.add_argument("--bundles", nargs="*", type=Path, default=())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("THIRDHAND_VA_CONFIG", "configs/vision.yaml")),
    )
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path(
            os.environ.get(
                "XVISIO_STREAM_EXECUTABLE",
                "build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream",
            )
        ),
    )
    parser.add_argument("--allow-camera", action="store_true")
    parser.add_argument(
        "--handeye",
        type=Path,
        default=(
            Path(os.environ["THIRDHAND_VA_HANDEYE"])
            if os.environ.get("THIRDHAND_VA_HANDEYE")
            else None
        ),
    )
    return parser


def consume_commands(
    store: ArmStateStore,
    selections: queue.SimpleQueue[tuple[int, str]],
    pose_resets: queue.SimpleQueue[tuple[str, int]] | None = None,
    releases: queue.SimpleQueue[str] | None = None,
) -> None:
    """Receive read-only robot state from the existing Node camera bridge."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if message.get("type") == "arm_state":
                store.update(message)
            if message.get("type") == "select_bottle":
                stable_id = message.get("stable_id")
                request_id = message.get("request_id")
                if (
                    isinstance(stable_id, int)
                    and not isinstance(stable_id, bool)
                    and 1 <= stable_id <= 5
                    and isinstance(request_id, str)
                    and request_id
                ):
                    selections.put((stable_id, request_id))
            if message.get("type") == "release_bottle":
                request_id = message.get("request_id")
                if releases is not None and isinstance(request_id, str) and request_id:
                    releases.put(request_id)
            if message.get("type") == "reset_target_pose_reference":
                request_id = message.get("request_id")
                motion_epoch = message.get("motion_epoch")
                if (
                    pose_resets is not None
                    and isinstance(request_id, str)
                    and request_id
                    and isinstance(motion_epoch, int)
                    and not isinstance(motion_epoch, bool)
                    and motion_epoch > 0
                ):
                    pose_resets.put((request_id, motion_epoch))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue


def emit_bridge_ready(
    events,
    config: VisionConfig,
    calibration: HandEyeCalibration | None,
    model_provenance: dict[str, str],
) -> None:
    message = {
        "type": "bridge_ready",
        "camera": "xvisio_rgbd",
        "camera_serial": config.camera_serial,
        "registration_id": config.camera_registration_id,
        "camera_mount_id": config.camera_mount_id,
        "vision_config_id": config.content_id,
        "calibration_id": None if calibration is None else calibration.content_id,
        "calibration_approved": bool(
            calibration is not None and calibration.approved_for_bottle_grasp
        ),
        "model_provenance": dict(model_provenance),
        "robot_control_enabled": False,
    }
    events.write(
        json.dumps(message, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    events.flush()


def emit_event(events, message: dict) -> None:
    events.write(
        json.dumps(message, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    events.flush()


class PendingSelectionController:
    """Keep one bottle-selection request alive until tracking can reserve it."""

    def __init__(self) -> None:
        self._pending: tuple[int, str] | None = None
        self._pending_reported = False

    def submit(self, stable_id: int, request_id: str) -> None:
        request = (stable_id, request_id)
        if request != self._pending:
            self._pending = request
            self._pending_reported = False

    def try_apply(self, pipeline) -> dict | None:
        if self._pending is None:
            return None
        stable_id, request_id = self._pending
        changed = pipeline.select(stable_id, request_id)
        accepted = changed or (
            pipeline.selection is not None
            and pipeline.selection.stable_id == stable_id
            and pipeline.selection.request_id == request_id
        )
        if accepted:
            self._pending = None
            self._pending_reported = False
            return {
                "type": "selection_status",
                "request_id": request_id,
                "stable_id": stable_id,
                "status": "accepted",
                "changed": changed,
                "robot_control_enabled": False,
            }
        if self._pending_reported:
            return None
        self._pending_reported = True
        return {
            "type": "selection_status",
            "request_id": request_id,
            "stable_id": stable_id,
            "status": "pending",
            "changed": False,
            "robot_control_enabled": False,
        }

    def release(self, pipeline, request_id: str) -> dict:
        selected_request = (
            None if pipeline.selection is None else pipeline.selection.request_id
        )
        pending_request = (
            None if self._pending is None else self._pending[1]
        )
        if pending_request == request_id:
            self._pending = None
            self._pending_reported = False
        pipeline.release(request_id)
        return {
            "type": "selection_release_status",
            "request_id": request_id,
            "status": (
                "released"
                if request_id in {selected_request, pending_request}
                else "not_reserved"
            ),
            "robot_control_enabled": False,
        }


def emit_vision_status(
    events: BinaryIO,
    decision: VisionDecision,
    provenance: FrameProvenance,
    *,
    latency_ms: float,
) -> None:
    """Keep the control site's health state tied to processed RGB-D frames."""
    emit_event(
        events,
        {
            "type": "vision_status",
            "ts": provenance.observed_at_ms,
            "online": True,
            "model_ready": True,
            "camera_ready": True,
            "canonical_rgb_source": "xvisio_rgb",
            "metric_depth_source": "xvisio_depth",
            "lumos_sequence": decision.frame_id,
            "registration_id": decision.registration_id,
            "motion_epoch": decision.motion_epoch,
            "latency_ms": float(latency_ms),
            "blockers": list(decision.reasons),
            "robot_control_enabled": False,
        },
    )


def assert_camera_access(args: argparse.Namespace) -> None:
    if args.source != "live":
        return
    env_allowed = os.environ.get("THIRDHAND_VA_ALLOW_CAMERA", "").lower() in {
        "1", "true", "yes",
    }
    if not args.allow_camera and not env_allowed:
        raise RuntimeError(
            "camera access is disabled; wait for calibration release, then pass "
            "--allow-camera or THIRDHAND_VA_ALLOW_CAMERA=1"
        )


def iter_frames(
    args: argparse.Namespace,
    config: VisionConfig,
    stop: threading.Event,
) -> Iterator[RgbdFrame]:
    assert_camera_access(args)
    if args.source == "replay":
        if not args.bundles:
            raise ValueError("replay source requires at least one --bundles path")
        for path in args.bundles:
            if stop.is_set():
                return
            yield read_frame_bundle(path)
        return
    sequence = -1
    last_frame_at = time.monotonic()
    with XVisioStream(args.executable, expected_serial=config.camera_serial) as stream:
        while not stop.is_set():
            frame = stream.read_after(sequence, timeout_s=0.25)
            if frame is None:
                if time.monotonic() - last_frame_at >= 5.0:
                    raise RuntimeError("camera frame timeout")
                continue
            sequence = frame.sequence
            last_frame_at = time.monotonic()
            yield frame


class LatestFrameMailbox:
    """Thread-safe single-slot mailbox that never queues stale camera frames."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._latest: RgbdFrame | None = None
        self._closed = False
        self._error: BaseException | None = None

    def publish(self, frame: RgbdFrame) -> bool:
        with self._condition:
            if self._closed:
                return False
            self._latest = frame
            self._condition.notify_all()
            return True

    def close(self, error: BaseException | None = None) -> None:
        with self._condition:
            self._closed = True
            if error is not None:
                self._error = error
            self._condition.notify_all()

    def wait_for_newer(
        self, sequence: int, *, timeout_s: float
    ) -> RgbdFrame | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while self._latest is None or self._latest.sequence <= sequence:
                if self._error is not None:
                    raise RuntimeError(
                        f"camera capture failed: {self._error}"
                    ) from self._error
                if self._closed:
                    return None
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest


def capture_and_publish_frames(
    *,
    frames: Iterable[RgbdFrame],
    mailbox: LatestFrameMailbox,
    raw_stream: BinaryIO,
    depth_stream: BinaryIO,
    min_depth_m: float,
    max_depth_m: float,
    stop: threading.Event,
    error_stream: BinaryIO | None = None,
) -> None:
    """Publish smooth previews while inference independently consumes latest."""
    error: BaseException | None = None
    try:
        for frame in frames:
            if stop.is_set():
                break
            provenance = FrameProvenance(
                frame.sequence, frame.monotonic_ns, int(time.time() * 1000)
            )
            try:
                raw_jpeg = encode_jpeg(frame.rgb)
                heatmap = render_depth_heatmap(
                    frame.depth_m,
                    min_depth_m=min_depth_m,
                    max_depth_m=max_depth_m,
                )
                depth_jpeg = encode_jpeg(heatmap)
            except Exception as preview_error:
                if error_stream is not None:
                    emit_event(
                        error_stream,
                        {
                            "type": "preview_encode_failed",
                            "frame_id": frame.sequence,
                            "error": str(preview_error),
                            "robot_control_enabled": False,
                        },
                    )
                if not mailbox.publish(frame):
                    break
                continue
            raw_stream.write(build_mjpeg_part(raw_jpeg, provenance))
            raw_stream.flush()
            depth_stream.write(build_mjpeg_part(depth_jpeg, provenance))
            depth_stream.flush()
            if not mailbox.publish(frame):
                break
    except BaseException as caught:
        error = caught
    finally:
        mailbox.close(error)


def start_capture_worker(
    *,
    frames: Iterable[RgbdFrame],
    mailbox: LatestFrameMailbox,
    raw_stream: BinaryIO,
    depth_stream: BinaryIO,
    min_depth_m: float,
    max_depth_m: float,
    stop: threading.Event,
    error_stream: BinaryIO | None = None,
) -> threading.Thread:
    """Start preview publication asynchronously and return its owner thread."""
    worker = threading.Thread(
        target=capture_and_publish_frames,
        kwargs={
            "frames": frames,
            "mailbox": mailbox,
            "raw_stream": raw_stream,
            "depth_stream": depth_stream,
            "min_depth_m": min_depth_m,
            "max_depth_m": max_depth_m,
            "stop": stop,
            "error_stream": error_stream,
        },
        daemon=True,
    )
    worker.start()
    return worker


def stop_capture_worker(
    *,
    frames: Iterable[RgbdFrame],
    mailbox: LatestFrameMailbox,
    stop: threading.Event,
    worker: threading.Thread,
    timeout_s: float,
) -> None:
    """Close a capture source and fail loudly if its worker cannot terminate."""
    stop.set()
    mailbox.close()
    close = getattr(frames, "close", None)
    if callable(close):
        try:
            close()
        except ValueError:
            # A running generator cannot be closed cross-thread. Its bounded
            # 250 ms camera wait observes ``stop`` and closes XVisio itself.
            pass
    worker.join(timeout=max(0.0, timeout_s))
    if worker.is_alive():
        raise RuntimeError("camera capture worker did not stop")


def run(args: argparse.Namespace) -> int:
    config = VisionConfig.from_yaml(args.config)
    calibration = (
        HandEyeCalibration.load(
            args.handeye,
            expected_camera_serial=config.camera_serial,
            expected_registration_id=config.camera_registration_id,
            expected_camera_mount_id=config.camera_mount_id,
        )
        if args.handeye is not None
        else None
    )
    if calibration is not None and calibration.camera_serial != config.camera_serial:
        raise RuntimeError("hand-eye calibration camera serial does not match config")
    arm_states = ArmStateStore()
    selections: queue.SimpleQueue[tuple[int, str]] = queue.SimpleQueue()
    pose_resets: queue.SimpleQueue[tuple[str, int]] = queue.SimpleQueue()
    releases: queue.SimpleQueue[str] = queue.SimpleQueue()
    pipeline = VisionPipeline(
        config,
        GroundedSamBackend(config, local_files_only=True),
    )
    selection_controller = PendingSelectionController()
    publisher = LatestFramePublisher()
    primary = sys.stdout.buffer
    events = os.fdopen(3, "wb", buffering=0, closefd=False)
    overlay = os.fdopen(4, "wb", buffering=0, closefd=False)
    raw_stream = os.fdopen(5, "wb", buffering=0, closefd=False)
    depth_stream = os.fdopen(6, "wb", buffering=0, closefd=False)
    threading.Thread(
        target=consume_commands,
        args=(arm_states, selections, pose_resets, releases),
        daemon=True,
    ).start()
    mailbox = LatestFrameMailbox()
    capture_stop = threading.Event()
    frames = iter_frames(args, config, capture_stop)
    capture_thread = start_capture_worker(
        frames=frames,
        mailbox=mailbox,
        raw_stream=raw_stream,
        depth_stream=depth_stream,
        min_depth_m=config.min_depth_m,
        max_depth_m=config.max_depth_m,
        stop=capture_stop,
        error_stream=events,
    )
    previous_finished_ns: int | None = None
    processed_sequence = -1
    bridge_ready_emitted = False
    try:
        while True:
            frame = mailbox.wait_for_newer(processed_sequence, timeout_s=5.0)
            if frame is None:
                if capture_thread.is_alive():
                    raise RuntimeError("camera preview frame timeout")
                return 0
            processed_sequence = frame.sequence
            while True:
                try:
                    request_id = releases.get_nowait()
                except queue.Empty:
                    break
                emit_event(events, selection_controller.release(pipeline, request_id))
            latest_selection = None
            while True:
                try:
                    latest_selection = selections.get_nowait()
                except queue.Empty:
                    break
            if latest_selection is not None:
                stable_id, request_id = latest_selection
                selection_controller.submit(stable_id, request_id)
            selection_event = selection_controller.try_apply(pipeline)
            if selection_event is not None:
                emit_event(events, selection_event)
            latest_pose_reset = None
            while True:
                try:
                    latest_pose_reset = pose_resets.get_nowait()
                except queue.Empty:
                    break
            if latest_pose_reset is not None:
                request_id, motion_epoch = latest_pose_reset
                try:
                    pipeline.begin_motion_epoch(motion_epoch)
                    reset_status = "accepted"
                except ValueError:
                    reset_status = "rejected"
                emit_event(
                    events,
                    {
                        "type": "target_pose_reference_status",
                        "request_id": request_id,
                        "motion_epoch": motion_epoch,
                        "status": reset_status,
                    },
                )
            latest_arm_state = arm_states.latest()
            pipeline.set_camera_moving(
                latest_arm_state is not None and (
                    not latest_arm_state.stationary
                    or frame.monotonic_ns
                    < latest_arm_state.stationary_since_monotonic_ns + 300_000_000
                )
            )
            started_ns = time.monotonic_ns()
            t_base_camera = None
            if calibration is not None and latest_arm_state is not None:
                arm_frame_delta_ns = abs(
                    frame.monotonic_ns - latest_arm_state.received_monotonic_ns
                )
                if arm_frame_delta_ns <= 250_000_000:
                    t_base_camera = rpy_xyz_transform(
                        latest_arm_state.flange_position_m,
                        latest_arm_state.flange_euler_rad,
                    ) @ calibration.t_flange_camera
            decision = pipeline.process(
                frame,
                now_ns=started_ns,
                t_base_camera=t_base_camera,
            )
            finished_ns = time.monotonic_ns()
            elapsed_ms = (finished_ns - started_ns) / 1_000_000
            fps = 0.0 if previous_finished_ns is None else 1e9 / max(
                1, finished_ns - previous_finished_ns
            )
            previous_finished_ns = finished_ns
            dino_ms, sam_ms = pipeline.backend.inference_timings_ms
            rendered = render_overlay(
                frame.rgb,
                decision,
                RenderMetrics(
                    fps=fps,
                    latency_ms=elapsed_ms,
                    dino_ms=dino_ms,
                    sam_ms=sam_ms,
                ),
                depth_m=frame.depth_m,
                min_depth_m=config.min_depth_m,
                max_depth_m=config.max_depth_m,
            )
            provenance = FrameProvenance(
                frame.sequence, frame.monotonic_ns, int(time.time() * 1000)
            )
            try:
                jpeg = encode_jpeg(rendered.image)
            except Exception as preview_error:
                emit_event(
                    events,
                    {
                        "type": "preview_encode_failed",
                        "frame_id": frame.sequence,
                        "error": str(preview_error),
                        "robot_control_enabled": False,
                    },
                )
                continue
            emit_vision_status(
                events,
                decision,
                provenance,
                latency_ms=elapsed_ms,
            )
            preview = None
            if calibration is not None:
                preview = build_base_grasp_preview(
                    decision,
                    calibration,
                    arm_states.latest(),
                    observed_at_ms=provenance.observed_at_ms,
                    now_monotonic_ns=time.monotonic_ns(),
                    frame_monotonic_ns=frame.monotonic_ns,
                    vision_config_id=config.content_id,
                    model_provenance=pipeline.backend.model_provenance(),
                )
            publisher.offer(
                jpeg,
                decision,
                provenance,
                grasp_preview=preview,
                model_provenance=pipeline.backend.model_provenance(),
            )
            if not bridge_ready_emitted:
                emit_bridge_ready(
                    events,
                    config,
                    calibration,
                    pipeline.backend.model_provenance(),
                )
                bridge_ready_emitted = True
            if not publisher.drain(primary, events, overlay):
                return 0
    finally:
        stop_capture_worker(
            frames=frames,
            mailbox=mailbox,
            stop=capture_stop,
            worker=capture_thread,
            timeout_s=6.0,
        )


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return run(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "type": "vision_error",
                    "robot_control_enabled": False,
                    "hardware_validation": "pending",
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
