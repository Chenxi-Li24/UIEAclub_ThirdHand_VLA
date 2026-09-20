#!/usr/bin/env python3
"""Observe one ordinal bottle with live XVisio RGB-D; never control the robot."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import numpy as np

from thirdhand_va.action.calibration.handeye import HandEyeCalibration, rpy_xyz_transform
from thirdhand_va.common.config import VisionConfig
from thirdhand_va.vision.camera.stream import XVisioStream
from thirdhand_va.vision.observer import (
    apply_rotated_mask_aspect_gate,
    attach_supervised_base_candidate,
    build_candidate_observations,
    capture_wall_time_ms,
    finalize_observation_freshness,
    find_locked_observation,
    wait_for_pose_covering_frame,
)
from thirdhand_va.vision.observer_evidence import (
    save_projection_failure_evidence,
    should_capture_projection_failure,
)
from thirdhand_va.vision.perception.bottle_filter import BottleCandidateFilter
from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend
from thirdhand_va.vision.supervised_nearfield import (
    add_reference_candidate, build_projection_observation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ordinal", type=int, required=True, help="1-based bottle from left")
    parser.add_argument("--allow-camera", action="store_true")
    parser.add_argument("--config", type=Path, default=Path("configs/vision.yaml"))
    parser.add_argument(
        "--executable",
        type=Path,
        default=Path("build/vision/xvisio_rgbd_stream/xvisio_rgbd_stream"),
    )
    parser.add_argument("--output-overlay", type=Path)
    parser.add_argument("--robot-pose-file", type=Path)
    parser.add_argument(
        "--handeye-parent-frame",
        choices=("sdk_tool",),
        help="explicit correction for the legacy calibration parent frame",
    )
    parser.add_argument(
        "--handeye",
        type=Path,
        default=Path("configs/calibration/lumos-handeye.pending.json"),
    )
    parser.add_argument("--max-attempts", type=int, default=8)
    parser.add_argument("--watch-jsonl", action="store_true")
    parser.add_argument("--max-observations", type=int)
    parser.add_argument(
        "--camera-start-timeout-s",
        type=float,
        default=15.0,
        help="first-frame startup budget only; subsequent frame timeout remains 5 s",
    )
    parser.add_argument(
        "--grasp-height-base-m",
        type=float,
        help="optional Base-Z surface band center; requires fresh stationary sdk_tool pose",
    )
    parser.add_argument("--observation-height-base-m", type=float,
                        help="Base-Z body band for XY observation, independent of commanded grasp Z")
    parser.add_argument("--bottle-diameter-m", type=float,
                        help="operator measured bottle diameter used only for surface-to-axis correction")
    args = parser.parse_args()
    if args.observation_height_base_m is not None:
        if args.grasp_height_base_m is not None:
            parser.error("choose only one observation height argument")
        args.grasp_height_base_m = args.observation_height_base_m
    if args.bottle_diameter_m is not None and (
        not np.isfinite(args.bottle_diameter_m) or not 0 < args.bottle_diameter_m <= 0.072
    ):
        parser.error("--bottle-diameter-m must be finite and in (0, 0.072]")
    if not args.allow_camera:
        print(json.dumps({
            "valid": False,
            "reason": "camera_access_not_authorized",
            "robot_control_enabled": False,
            "execution_enabled": False,
        }, sort_keys=True))
        return 2
    if args.ordinal <= 0 or args.max_attempts <= 0:
        raise SystemExit("--ordinal and --max-attempts must be positive")
    if not np.isfinite(args.camera_start_timeout_s) or args.camera_start_timeout_s <= 0:
        raise SystemExit("--camera-start-timeout-s must be finite and positive")
    if args.grasp_height_base_m is not None and (
        not np.isfinite(args.grasp_height_base_m)
        or args.grasp_height_base_m <= 0
        or not args.watch_jsonl
    ):
        raise SystemExit(
            "--grasp-height-base-m must be finite, positive, and used with --watch-jsonl"
        )

    config = VisionConfig.from_yaml(args.config)
    backend_config = (
        replace(config, redetect_interval_frames=1_000_000)
        if args.watch_jsonl else config
    )
    backend = GroundedSamBackend(backend_config, local_files_only=True)
    bottle_filter = BottleCandidateFilter(config)
    calibration = HandEyeCalibration.load(
        args.handeye,
        expected_camera_serial=config.camera_serial,
        expected_registration_id=config.camera_registration_id,
        expected_camera_mount_id=config.camera_mount_id,
    )
    locked_id: int | None = None
    selected = None
    observations = ()
    frame = None
    candidates = ()

    if args.watch_jsonl:
        emitted = 0
        failure_evidence_attempted = False
        try:
            with XVisioStream(args.executable, expected_serial=config.camera_serial) as stream:
                seed = stream.read_after(-1, timeout_s=args.camera_start_timeout_s)
                if seed is None:
                    raise RuntimeError(
                        "camera frame timeout during detection seed after "
                        f"{args.camera_start_timeout_s:.3f}s: "
                        f"{json.dumps(stream.diagnostics(), sort_keys=True)}"
                    )
                seed_base = bottle_filter.filter(seed.rgb, backend.infer(seed.rgb))
                seed_adjusted = [apply_rotated_mask_aspect_gate(item, config) for item in seed_base]
                seed_candidates = tuple(item[0] for item in seed_adjusted)
                seed_rows = build_candidate_observations(
                    seed, seed_candidates, config, now_monotonic_ns=time.monotonic_ns()
                )
                if args.ordinal > len(seed_rows):
                    print(json.dumps({
                        "event": "bottle_observation",
                        "valid": False,
                        "camera_observation_valid": False,
                        "geometry_valid": False,
                        "reason": "ordinal_not_visible",
                        "requested_ordinal": args.ordinal,
                        "visible_bottles": len(seed_rows),
                        "robot_control_enabled": False,
                        "execution_enabled": False,
                    }, sort_keys=True), flush=True)
                    return 3
                locked_id = int(seed_rows[args.ordinal - 1]["detection_id"])
                sequence = seed.sequence
                while True:
                    frame = stream.read_after(sequence, timeout_s=5.0)
                    if frame is None:
                        print(json.dumps({
                            "event": "bottle_observation",
                            "valid": False,
                            "camera_observation_valid": False,
                            "geometry_valid": False,
                            "reason": "camera_frame_timeout",
                            "target_id": f"detection:{locked_id}",
                            "track_state": "lost",
                            "robot_control_enabled": False,
                            "execution_enabled": False,
                        }, sort_keys=True), flush=True)
                        return 3
                    sequence = frame.sequence
                    base_candidates = bottle_filter.filter(frame.rgb, backend.infer(frame.rgb))
                    adjusted = [apply_rotated_mask_aspect_gate(item, config) for item in base_candidates]
                    candidates = tuple(item[0] for item in adjusted)
                    shape_metrics = {
                        item.detection_id: (ratio, recovered)
                        for item, ratio, recovered in adjusted
                    }
                    pose_for_frame = None
                    t_base_camera_for_frame = None
                    upright_direction_camera = None
                    if args.robot_pose_file is not None:
                        orientation_check_wall_ms = int(time.time() * 1000)
                        orientation_capture_wall_ms = capture_wall_time_ms(
                            captured_monotonic_ns=frame.monotonic_ns,
                            now_monotonic_ns=time.monotonic_ns(),
                            now_wall_ms=orientation_check_wall_ms,
                        )
                        pose_for_frame = wait_for_pose_covering_frame(
                            lambda: json.loads(
                                args.robot_pose_file.read_text(encoding="utf-8")
                            ),
                            capture_wall_ms=orientation_capture_wall_ms,
                            captured_monotonic_ns=frame.monotonic_ns,
                        )
                        orientation_check_wall_ms = int(time.time() * 1000)
                        try:
                            position = np.asarray(
                                pose_for_frame["tcp_position_m"], dtype=float
                            )
                            euler = np.asarray(
                                pose_for_frame["tcp_euler_rad"], dtype=float
                            )
                            pose_ts_for_orientation = pose_for_frame.get("ts")
                            stationary_since_for_orientation = pose_for_frame.get(
                                "stationary_since_ms"
                            )
                            pose_covers_frame = (
                                pose_for_frame.get("stationary") is True
                                and isinstance(pose_ts_for_orientation, int)
                                and not isinstance(pose_ts_for_orientation, bool)
                                and 0
                                <= orientation_check_wall_ms - pose_ts_for_orientation
                                <= 500
                                and isinstance(stationary_since_for_orientation, int)
                                and not isinstance(stationary_since_for_orientation, bool)
                                and stationary_since_for_orientation
                                <= orientation_capture_wall_ms
                                <= pose_ts_for_orientation
                            )
                            if (
                                args.handeye_parent_frame == "sdk_tool"
                                and pose_for_frame.get("pose_frame") == "sdk_tool"
                                and pose_covers_frame
                                and position.shape == (3,)
                                and euler.shape == (3,)
                                and np.isfinite(position).all()
                                and np.isfinite(euler).all()
                            ):
                                t_base_camera_for_frame = (
                                    rpy_xyz_transform(position, euler)
                                    @ calibration.t_flange_camera
                                )
                                upright_direction_camera = (
                                    t_base_camera_for_frame[:3, :3].T
                                    @ np.asarray([0.0, 0.0, 1.0])
                                )
                        except (KeyError, TypeError, ValueError):
                            pass
                    observations = build_candidate_observations(
                        frame,
                        candidates,
                        config,
                        now_monotonic_ns=time.monotonic_ns(),
                        upright_direction_camera=upright_direction_camera,
                        t_base_camera=t_base_camera_for_frame,
                        grasp_height_base_m=args.grasp_height_base_m,
                    )
                    for row in observations:
                        ratio, recovered = shape_metrics[row["detection_id"]]
                        row.update({
                            "oriented_mask_aspect_ratio": ratio,
                            "rotated_aspect_recovered": recovered,
                            "physical_upright_verified": False,
                        })
                    selected = find_locked_observation(observations, detection_id=locked_id)
                    if selected is None:
                        payload = {
                            "valid": False,
                            "camera_observation_valid": False,
                            "geometry_valid": False,
                            "reason": "target_lost",
                            "reasons": ["target_lost"],
                            "target_id": f"detection:{locked_id}",
                            "locked_detection_id": locked_id,
                            "track_state": "lost",
                        }
                    else:
                        payload = dict(selected)
                        payload["track_state"] = "locked"
                    payload.update({
                        "event": "bottle_observation",
                        "frame_id": frame.sequence,
                        "captured_monotonic_ns": frame.monotonic_ns,
                        "camera_serial": config.camera_serial,
                        "registration_id": config.camera_registration_id,
                        "calibration_id": calibration.content_id,
                        "requested_ordinal": args.ordinal,
                        "locked_detection_id": locked_id,
                        "robot_control_enabled": False,
                        "execution_enabled": False,
                        "candidate_offset_base_m_applied": [0.0, 0.0, 0.0],
                        "requested_grasp_height_base_m": args.grasp_height_base_m,
                        "grasp_height_half_band_m": (
                            0.005 if args.grasp_height_base_m is not None else None
                        ),
                        "all_candidates": list(observations),
                        "handeye": {
                            "calibration_id": calibration.content_id,
                            "source_matrix_label": "T_flange_camera",
                            "effective_matrix_semantics": (
                                "T_sdk_tool_camera"
                                if args.handeye_parent_frame == "sdk_tool" else None
                            ),
                            "physically_validated": False,
                            "approved_for_bottle_grasp": False,
                        },
                    })
                    if args.robot_pose_file is not None:
                        assert pose_for_frame is not None
                        pose = pose_for_frame
                        capture_wall_ms = capture_wall_time_ms(
                            captured_monotonic_ns=frame.monotonic_ns,
                            now_monotonic_ns=time.monotonic_ns(),
                            now_wall_ms=int(time.time() * 1000),
                        )
                        pose_ts = pose.get("ts")
                        stationary_since_ms = pose.get("stationary_since_ms")
                        valid_pose_ts = (
                            isinstance(pose_ts, int) and not isinstance(pose_ts, bool)
                        )
                        pose_age_ms = (
                            None if not valid_pose_ts
                            else int(time.time() * 1000) - pose_ts
                        )
                        pose_blockers = []
                        if args.handeye_parent_frame != "sdk_tool":
                            pose_blockers.append("explicit_sdk_tool_handeye_parent_frame_required")
                        if pose.get("pose_frame") != "sdk_tool":
                            pose_blockers.append("sdk_tool_pose_required")
                        if pose.get("stationary") is not True:
                            pose_blockers.append("pose_not_stationary")
                        if not (
                            isinstance(stationary_since_ms, int)
                            and not isinstance(stationary_since_ms, bool)
                            and stationary_since_ms <= capture_wall_ms
                            and valid_pose_ts
                            and pose_ts >= capture_wall_ms
                        ):
                            pose_blockers.append("pose_does_not_cover_frame_capture")
                        if pose_age_ms is None or pose_age_ms < 0 or pose_age_ms > 500:
                            pose_blockers.append("robot_pose_stale")
                        pose_vectors_valid = False
                        if pose.get("pose_frame") == "sdk_tool":
                            try:
                                position = np.asarray(pose["tcp_position_m"], dtype=float)
                                euler = np.asarray(pose["tcp_euler_rad"], dtype=float)
                                pose_vectors_valid = (
                                    position.shape == (3,)
                                    and euler.shape == (3,)
                                    and np.isfinite(position).all()
                                    and np.isfinite(euler).all()
                                )
                            except (KeyError, TypeError, ValueError):
                                pose_vectors_valid = False
                        if not pose_vectors_valid:
                            pose_blockers.append("sdk_tool_pose_invalid")
                        payload = attach_supervised_base_candidate(
                            payload,
                            t_base_camera=t_base_camera_for_frame,
                            pose_blockers=pose_blockers,
                            bottle_diameter_m=args.bottle_diameter_m,
                        )
                        payload.update({
                            "robot_state_ts": pose_ts,
                            "robot_pose_age_ms": pose_age_ms,
                            "robot_pose_blockers": pose_blockers,
                        })
                    else:
                        payload.update({
                            "base_xyz_m": None,
                            "robot_state_ts": None,
                            "robot_pose_blockers": ["robot_pose_missing"],
                            "supervised_base_candidate_valid": False,
                            "base_transform_approved": False,
                        })
                    final_mono = time.monotonic_ns()
                    wall_ms = int(time.time() * 1000)
                    payload = finalize_observation_freshness(
                        payload,
                        captured_monotonic_ns=frame.monotonic_ns,
                        now_monotonic_ns=final_mono,
                        max_frame_age_ms=config.max_frame_age_ms,
                    )
                    payload["supervised_base_candidate_valid"] = bool(
                        payload.get("supervised_base_candidate_valid")
                        and payload.get("valid")
                    )
                    payload["observed_at_ms"] = capture_wall_time_ms(
                        captured_monotonic_ns=frame.monotonic_ns,
                        now_monotonic_ns=final_mono,
                        now_wall_ms=wall_ms,
                    )
                    payload["emitted_at_ms"] = wall_ms
                    locked_candidate = next(
                        (item for item in candidates if item.detection_id == locked_id), None
                    )
                    if pose_for_frame and pose_for_frame.get("supervised_anchor"):
                        payload = build_projection_observation(
                            payload, frame=frame, candidate=locked_candidate,
                            pose=pose_for_frame, t_base_camera=t_base_camera_for_frame,
                        )
                    elif (pose_for_frame
                          and pose_for_frame.get("controller_phase") in ("idle", "aborted", "hover")
                          and pose_for_frame.get("pending_phase") is None):
                        payload = add_reference_candidate(
                            payload, frame=frame, candidate=locked_candidate,
                            t_base_camera=t_base_camera_for_frame,
                            observation_height_m=args.grasp_height_base_m,
                            bottle_diameter_m=args.bottle_diameter_m,
                        )
                    print(json.dumps(payload, sort_keys=True), flush=True)
                    if (
                        args.output_overlay is not None
                        and not failure_evidence_attempted
                        and should_capture_projection_failure(payload, locked_candidate)
                    ):
                        failure_evidence_attempted = True
                        write_started_at_ms = int(time.time() * 1000)
                        try:
                            evidence = save_projection_failure_evidence(
                                args.output_overlay,
                                frame=frame,
                                candidate=locked_candidate,
                                payload=payload,
                                write_started_at_ms=write_started_at_ms,
                            )
                            print(json.dumps(evidence, sort_keys=True), flush=True)
                        except (OSError, TypeError, ValueError, cv2.error) as exc:
                            print(json.dumps({
                                "event": "projection_failure_evidence_save_failed",
                                "frame_id": frame.sequence,
                                "write_started_at_ms": write_started_at_ms,
                                "error": str(exc),
                                "robot_control_enabled": False,
                                "execution_enabled": False,
                            }, sort_keys=True), flush=True)
                    emitted += 1
                    if selected is None:
                        return 3
                    if args.max_observations is not None and emitted >= args.max_observations:
                        return 0
        except KeyboardInterrupt:
            print(json.dumps({
                "event": "observer_stream_end",
                "valid": False,
                "camera_observation_valid": False,
                "geometry_valid": False,
                "reason": "observer_interrupted",
                "target_id": None if locked_id is None else f"detection:{locked_id}",
                "robot_control_enabled": False,
                "execution_enabled": False,
            }, sort_keys=True), flush=True)
            return 130

    with XVisioStream(args.executable, expected_serial=config.camera_serial) as stream:
        # Detection/model warmup establishes the ordinal once. Its old timestamp
        # is never reused as a fresh observation.
        seed = stream.read_after(-1, timeout_s=args.camera_start_timeout_s)
        if seed is None:
            raise RuntimeError(
                "camera frame timeout during detection seed after "
                f"{args.camera_start_timeout_s:.3f}s: "
                f"{json.dumps(stream.diagnostics(), sort_keys=True)}"
            )
        seed_base = bottle_filter.filter(seed.rgb, backend.infer(seed.rgb))
        seed_adjusted = [apply_rotated_mask_aspect_gate(item, config) for item in seed_base]
        seed_candidates = tuple(item[0] for item in seed_adjusted)
        seed_rows = build_candidate_observations(
            seed,
            seed_candidates,
            config,
            now_monotonic_ns=time.monotonic_ns(),
        )
        if args.ordinal > len(seed_rows):
            result = {
                "valid": False,
                "reason": "ordinal_not_visible",
                "requested_ordinal": args.ordinal,
                "visible_bottles": len(seed_rows),
            }
        else:
            locked_id = int(seed_rows[args.ordinal - 1]["detection_id"])
            result = None
            for _ in range(args.max_attempts):
                frame = stream.read_after(seed.sequence if frame is None else frame.sequence, 5.0)
                if frame is None:
                    continue
                base_candidates = bottle_filter.filter(frame.rgb, backend.infer(frame.rgb))
                adjusted = [
                    apply_rotated_mask_aspect_gate(item, config)
                    for item in base_candidates
                ]
                candidates = tuple(item[0] for item in adjusted)
                shape_metrics = {
                    item.detection_id: (ratio, recovered)
                    for item, ratio, recovered in adjusted
                }
                observations = build_candidate_observations(
                    frame,
                    candidates,
                    config,
                    now_monotonic_ns=time.monotonic_ns(),
                )
                for row in observations:
                    ratio, recovered = shape_metrics[row["detection_id"]]
                    row["oriented_mask_aspect_ratio"] = ratio
                    row["rotated_aspect_recovered"] = recovered
                    row["physical_upright_verified"] = False
                selected = find_locked_observation(observations, detection_id=locked_id)
                if selected is None:
                    result = {"valid": False, "reason": "target_lost"}
                    break
                if "frame_stale" not in selected["reasons"]:
                    result = dict(selected)
                    break
            if result is None:
                result = (
                    {"valid": False, "reason": "fresh_observation_unavailable"}
                    if selected is None else dict(selected)
                )

    result.update({
        "requested_ordinal": args.ordinal,
        "locked_detection_id": locked_id,
        "frame_id": None if frame is None else frame.sequence,
        "captured_monotonic_ns": None if frame is None else frame.monotonic_ns,
        "camera_serial": config.camera_serial,
        "registration_id": config.camera_registration_id,
        "robot_control_enabled": False,
        "execution_enabled": False,
        "all_candidates": list(observations),
    })

    result["handeye"] = {
        "calibration_id": calibration.content_id,
        "source_matrix_label": "T_flange_camera",
        "effective_matrix_semantics": (
            None if args.handeye_parent_frame is None else "T_sdk_tool_camera"
        ),
        "semantic_correction_evidence":
            "artifacts/test1-coordinate-frame-evidence-20260908.md",
        "numerically_validated": calibration.numerically_validated,
        "physically_validated": calibration.physically_validated,
        "approved_for_bottle_grasp": calibration.approved_for_bottle_grasp,
    }
    result["candidate_offset_base_m_applied"] = [0.0, 0.0, 0.0]
    if args.robot_pose_file is not None:
        pose = json.loads(args.robot_pose_file.read_text(encoding="utf-8"))
        result["robot_pose_used"] = pose
        pose_timestamp_ms = pose.get("ts")
        if pose_timestamp_ms is None and isinstance(pose.get("timestamp"), str):
            pose_timestamp_ms = int(datetime.fromisoformat(pose["timestamp"]).timestamp() * 1000)
        result["robot_state_ts"] = pose_timestamp_ms
        pose_age_ms = None if pose_timestamp_ms is None else int(time.time() * 1000) - int(pose_timestamp_ms)
        result["robot_pose_age_ms"] = pose_age_ms
        stationary = pose.get("stationary") is True
        if pose.get("schema") == "thirdhand-read-grasp-robot-pose-v1":
            velocities = [abs(float(item["velocity_rad_s"])) for item in pose["motor_feedback"]]
            stationary = max(velocities, default=float("inf")) <= 0.03
        pose_blockers = []
        if args.handeye_parent_frame != "sdk_tool":
            pose_blockers.append("explicit_sdk_tool_handeye_parent_frame_required")
        if not stationary:
            pose_blockers.append("pose_not_stationary")
        if pose_age_ms is None or pose_age_ms < 0 or pose_age_ms > 500:
            pose_blockers.append("robot_pose_stale")
        camera_xyz = result.get("camera_xyz_m")
        t_base_parent = None
        if args.handeye_parent_frame == "sdk_tool":
            if pose.get("pose_frame") == "sdk_tool":
                t_base_parent = rpy_xyz_transform(
                    pose["tcp_position_m"], pose["tcp_euler_rad"]
                )
            elif pose.get("schema") == "thirdhand-read-grasp-robot-pose-v1":
                t_base_parent = np.asarray(
                    pose["base_from_sdk_tool"]["matrix_4x4"], dtype=float
                )
            else:
                pose_blockers.append("sdk_tool_pose_required")
        if camera_xyz is not None and t_base_parent is not None:
            t_base_camera = t_base_parent @ calibration.t_flange_camera
            result["base_xyz_m"] = (
                t_base_camera @ np.asarray([*camera_xyz, 1.0], dtype=float)
            )[:3].tolist()
        result["robot_pose_blockers"] = pose_blockers
        result["supervised_base_candidate_valid"] = not pose_blockers
        result["base_transform_approved"] = False
    else:
        result.update({
            "base_xyz_m": None,
            "robot_pose_used": None,
            "robot_state_ts": None,
            "base_transform_approved": False,
            "supervised_base_candidate_valid": False,
        })

    if args.output_overlay is not None and frame is not None:
        image = cv2.cvtColor(frame.rgb, cv2.COLOR_RGB2BGR)
        by_id = {item.detection_id: item for item in candidates}
        for row in observations:
            item = by_id.get(row["detection_id"])
            if item is None:
                continue
            color = (0, 255, 255) if row["detection_id"] == locked_id else (0, 200, 0)
            contours, _ = cv2.findContours(
                item.mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            cv2.drawContours(image, contours, -1, color, 2)
            x0, y0, x1, y1 = (int(round(value)) for value in row["bbox"])
            cv2.rectangle(image, (x0, y0), (x1, y1), color, 2)
            cv2.putText(
                image,
                f"L{row['left_ordinal']} id={row['detection_id']} depth={row['depth_valid_ratio']:.2f}",
                (x0, max(20, y0 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2.LINE_AA,
            )
        args.output_overlay.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.output_overlay), image):
            raise RuntimeError(f"failed to write overlay: {args.output_overlay}")
        result["overlay_path"] = str(args.output_overlay.resolve())

    emitted_monotonic_ns = time.monotonic_ns()
    emitted_at_ms = int(time.time() * 1000)
    if frame is not None:
        result = finalize_observation_freshness(
            result,
            captured_monotonic_ns=frame.monotonic_ns,
            now_monotonic_ns=emitted_monotonic_ns,
            max_frame_age_ms=config.max_frame_age_ms,
        )
        result["observed_at_ms"] = capture_wall_time_ms(
            captured_monotonic_ns=frame.monotonic_ns,
            now_monotonic_ns=emitted_monotonic_ns,
            now_wall_ms=emitted_at_ms,
        )
    else:
        result["observed_at_ms"] = None
    result["emitted_at_ms"] = emitted_at_ms

    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("valid") else 3


if __name__ == "__main__":
    raise SystemExit(main())
