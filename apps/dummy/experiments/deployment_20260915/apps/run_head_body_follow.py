#!/usr/bin/env python3
"""Experimental head-body 2D follow loop.

Default mode is dry-run: it reads the same target stream as Dummy and prints
small J1-J6 targets without opening Robot Service.  Add --enable-motion only
for supervised, low-rate hardware tests.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy_legacy.config import load_config
from dummy_legacy.dume_touch_r1_follow import DumeTouchR1FollowController
from dummy_legacy.follow_loop_state import clamp_to_workspace_guard, should_advance_local_joints
from dummy_legacy.image_jacobian_servo import ImageJacobianServo
from dummy_legacy.motion_gate import require_motion_enable
from dummy_legacy.single_instance import SingleInstanceLock
from dummy_legacy.touch_r1_adapter import TouchR1Adapter
from dummy_legacy.tracker import HumanTracker
from dummy_legacy.vision_service_tracker import VisionServiceTracker
from dummy_legacy.workspace_guard import WorkspaceGuard


def parse_joints(value):
    joints = [float(part.strip()) for part in str(value).split(",")]
    if len(joints) != 6:
        raise argparse.ArgumentTypeError("--joints must contain six comma-separated numbers")
    return joints


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run experimental head-body visual follow")
    parser.add_argument(
        "--enable-motion",
        action="store_true",
        help="send low-rate move_joint commands to the real robot",
    )
    parser.add_argument(
        "--joints",
        type=parse_joints,
        default=None,
        help="dry-run starting joints in degrees, comma-separated J1..J6",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=6.0,
        help="control loop rate; keep hardware tests in the 5-10 Hz range",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=0,
        help="stop after N loop iterations; useful for dry-run smoke tests",
    )
    parser.add_argument(
        "--robot-ws",
        default="ws://127.0.0.1:31023/ws",
        help="Robot command WebSocket; hardware experiments default to the 31023 debug gateway",
    )
    parser.add_argument(
        "--robot-health",
        default="http://127.0.0.1:3000/health",
        help="Robot Service health URL used by the adapter",
    )
    parser.add_argument(
        "--skip-home",
        action="store_true",
        help="debug only: start following from the current pose instead of first returning to Home",
    )
    return parser.parse_args(argv)


def build_tracker(config):
    if config.get("vision_service", {}).get("enabled", True):
        return VisionServiceTracker(config), "vision_service"
    return HumanTracker(config), "opencv_v4l"


async def run_loop(config, args):
    controller = DumeTouchR1FollowController(config)
    image_servo = ImageJacobianServo(config) if args.enable_motion else None
    workspace_guard = WorkspaceGuard(config)
    tracker, tracker_mode = build_tracker(config)
    period = 1.0 / max(0.5, float(args.hz))
    if args.enable_motion and period < 0.2:
        period = 0.2

    adapter = None
    joints = args.joints or config.get("robot", {}).get(
        "home_joints_deg",
        [-0.163927, -2.611904, -4, 33.058620, 0.338783, 0.185784],
    )
    if args.enable_motion:
        config.setdefault("robot", {})
        config["robot"]["ws_url"] = args.robot_ws
        config["robot"]["health_url"] = args.robot_health
        config["robot"]["home_joints_deg"] = None
        config["robot"]["home_preset_name"] = "zero"
        adapter = TouchR1Adapter(config)
        await adapter.connect()
        if not args.skip_home:
            print("[dummy] returning to Robot Service zero preset before head-body follow", flush=True)
            await adapter.go_home()
        state = await adapter.get_state()
        if len(state.joints_deg) == 6:
            joints = list(state.joints_deg)
    controller.reset(joints)
    if image_servo is not None:
        image_servo.reset(joints)

    opened = tracker.open() if hasattr(tracker, "open") else True
    print(
        f"[dummy] head-body follow mode tracker={tracker_mode} open={opened} "
        f"motion={'enabled' if args.enable_motion else 'dry-run'} hz={1.0 / period:.1f}",
        flush=True,
    )
    mink = getattr(controller, "mink", None)
    if mink is not None:
        print(
            "[dummy] mink "
            f"{'available' if getattr(mink, 'available', False) else 'fallback'} "
            f"reason={getattr(mink, 'unavailable_reason', None)}",
            flush=True,
        )
    if image_servo is not None and image_servo.available:
        print("[dummy] follow control: 2D target -> image servo J1/J4 gimbal -> Touch R1 SDK", flush=True)
    else:
        print("[dummy] follow control: real/virtual 3D target -> Mink IK -> Touch R1 SDK", flush=True)

    frames = 0
    last_log = 0.0
    last_workspace_recovery = 0.0
    try:
        while True:
            if tracker_mode == "vision_service":
                target, _frame, error = tracker.read_frame()
                debug = dict(getattr(tracker, "last_debug", {}) or {})
                if error and time.time() - last_log > 2.0:
                    print(f"[dummy] vision warning: {error}", flush=True)
                    last_log = time.time()
            else:
                target = tracker.read()
                debug = dict(getattr(tracker, "last_debug", {}) or {})

            if args.enable_motion and adapter is not None:
                state = await adapter.get_state()
                if len(state.joints_deg) == 6:
                    joints = list(state.joints_deg)

            if image_servo is not None and image_servo.available:
                image_command = image_servo.update(joints, target)
                target_found = bool(image_command.ok)
                command = image_command.joints_deg
                source = f"image_servo/{image_command.reason}"
                servo_debug = image_command.debug or {}
                error_px = image_command.error_px
                depth_source = "2d_only"
                depth_m = 0.0
            else:
                follow_command = controller.target_for(joints, target, debug=debug)
                target_found = follow_command.target_found
                command = follow_command.joints_deg
                source = follow_command.source
                servo_debug = follow_command.debug or {}
                error_px = servo_debug.get("image_error_px") if hasattr(follow_command, "debug") else None
                if error_px is None:
                    error_px = follow_command.visual.error_px
                depth_source = servo_debug.get("estimated_depth_source", "-")
                depth_m = float(servo_debug.get("estimated_depth_m", 0.0))
            if target_found:
                raw_command = list(command)
                command, guard_exact, guard_reason = clamp_to_workspace_guard(joints, raw_command, workspace_guard)
                guard_ok, _guard_check_reason = workspace_guard.check(command)
                ex, ey = float(error_px[0]), float(error_px[1])
                rgbd_mode = "3D" if getattr(target, "depth_valid", False) else ("2D" if hasattr(target, "depth_valid") else "none")
                print(
                    "[dummy] target "
                    f"{target.kind} source={source} rgbd={rgbd_mode} "
                    f"depth={depth_source}:{depth_m:.2f}m "
                    f"err=({ex:.0f},{ey:.0f}) "
                    f"guard={'ok' if guard_exact else ('clamped' if guard_ok else 'reject')}:{guard_reason} "
                    f"q=[{', '.join(f'{value:.2f}' for value in command)}]",
                    flush=True,
                )
                if not guard_ok:
                    current_ok, current_reason = workspace_guard.check(joints)
                    if (
                        args.enable_motion
                        and adapter is not None
                        and not current_ok
                        and time.time() - last_workspace_recovery > 2.0
                    ):
                        last_workspace_recovery = time.time()
                        print(
                            "[dummy] workspace recovery: current pose is outside base-plane guard "
                            f"({current_reason}); returning to zero preset",
                            flush=True,
                        )
                        try:
                            state = await adapter.go_home()
                            if len(state.joints_deg) == 6:
                                joints = list(state.joints_deg)
                                controller.reset(joints)
                                if image_servo is not None:
                                    image_servo.reset(joints)
                        except (ValueError, RuntimeError, TimeoutError) as exc:
                            print(f"[dummy] workspace recovery failed: {exc}", flush=True)
                    await asyncio.sleep(period)
                    frames += 1
                    if args.max_frames and frames >= args.max_frames:
                        return
                    continue
                if args.enable_motion and adapter is not None:
                    sent = False
                    try:
                        before = list(joints)
                        sent = await adapter.send_joint_target(
                            command,
                            time_sec=max(0.35, period * 1.6),
                            skip_if_busy=False,
                        )
                        delta = max(abs(float(a) - float(b)) for a, b in zip(command, before)) if len(before) == 6 else 0.0
                        print(f"[dummy] motion sent={sent} max_delta={delta:.2f}deg", flush=True)
                    except (ValueError, RuntimeError, TimeoutError) as exc:
                        print(f"[dummy] motion command skipped: {exc}", flush=True)
                else:
                    sent = False
                if should_advance_local_joints(enable_motion=args.enable_motion, guard_ok=guard_ok, sent=sent):
                    joints = list(command)
            else:
                print(f"[dummy] no fresh target kind={target.kind}", flush=True)

            frames += 1
            if args.max_frames and frames >= args.max_frames:
                return
            await asyncio.sleep(period)
    finally:
        tracker.close()
        if adapter is not None:
            await adapter.close()


def run(argv=None):
    args = parse_args(argv)
    try:
        if args.enable_motion:
            require_motion_enable(True)
        cfg = load_config()
        # Hardware runs always start from the commissioned Robot Service zero pose
        # unless --skip-home is supplied for a narrow debug case.
        cfg.setdefault("robot", {})["go_home_on_start"] = bool(args.enable_motion and not args.skip_home)
        if args.enable_motion:
            cfg["robot"]["max_relative_move_deg"] = 0.8
            cfg["robot"]["min_command_interval_s"] = 0.22
            cfg["robot"]["follow_speed_percent"] = 0.05
            cfg["robot"]["follow_command"] = "move_joint"
            cfg["robot"]["follow_wait_complete"] = False
            cfg["robot"]["follow_ack_timeout_s"] = 0.8
            cfg["robot"]["servo_min_time_sec"] = 0.35
            cfg["robot"]["joint_limits_deg"] = [
                [-162, 162],
                [-12, 201],
                [-183, 0],
                [-98, 98],
                [-98, 98],
                [-164, 164],
            ]
            jacobian = cfg.setdefault("image_jacobian_servo", {})
            jacobian["enabled"] = True
            jacobian["deadzone_px"] = 24
            jacobian["gain"] = 0.35
            jacobian["max_step_deg"] = 0.55
            jacobian["max_excursion_deg"] = 80.0
            jacobian["damping"] = 0.01
            jacobian["divergence_px"] = 9999.0
            jacobian["min_response_norm_px_per_deg"] = 0.2
            jacobian["calibration_path"] = ""
            jacobian["axes"] = [
                {
                    "name": "J1_yaw_gimbal",
                    "joint_index": 0,
                    "px_per_deg": [4.0, -0.4],
                    "max_step_deg": 0.55,
                    "max_excursion_deg": 85.0,
                    "weight": 1.0,
                },
                {"name": "J2_disabled", "joint_index": 1, "px_per_deg": [0.0, 0.0], "enabled": False},
                {"name": "J3_disabled", "joint_index": 2, "px_per_deg": [0.0, 0.0], "enabled": False},
                {
                    "name": "J4_tilt_micro",
                    "joint_index": 3,
                    "px_per_deg": [0.9, -3.7],
                    "max_step_deg": 0.08,
                    "max_excursion_deg": 4.0,
                    "min_deg": -1.5,
                    "max_deg": 4.0,
                    "weight": 0.25,
                },
                {"name": "J5_disabled", "joint_index": 4, "px_per_deg": [0.0, 0.0], "enabled": False},
                {"name": "J6_disabled", "joint_index": 5, "px_per_deg": [0.0, 0.0], "enabled": False},
            ]
            distance = cfg.setdefault("distance_follow", {})
            distance["enabled"] = True
            distance["desired_depth_m"] = 0.30
            distance["deadband_m"] = 0.05
            distance["too_close_m"] = 0.30
            distance["far_depth_m"] = 1.15
            distance["curious_depth_m"] = 1.65
            distance["depth_lost_far_reach_after_s"] = 0.40
            distance["posture_step_deg"] = 0.35
            distance["active_joint_indices"] = []
            distance["far_reach_pose_deg"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            distance["curious_reach_pose_deg"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            distance["hold_pose_deg"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            distance["retract_pose_deg"] = [0.0, -2.0, -4.0, -6.0, 0.0, 0.0]
            mono = cfg.setdefault("monocular_depth", {})
            mono["enabled"] = True
            mono["focal_px"] = 520.0
            mono["assumed_body_height_m"] = 0.45
            mono["assumed_face_height_m"] = 0.22
            mono["min_bbox_h_px"] = 35.0
            mono["min_depth_m"] = 0.45
            mono["max_depth_m"] = 2.50
            mono["smoothing_alpha"] = 0.30
            virtual = cfg.setdefault("virtual_3d_target", {})
            virtual["enabled"] = True
            virtual["default_depth_m"] = 1.50
            virtual["max_gaze_depth_m"] = 1.80
            virtual["focal_px"] = 520.0
            virtual["max_x_m"] = 0.65
            virtual["max_y_m"] = 0.45
            virtual["smoothing_alpha"] = 0.35
            lock = cfg.setdefault("person_lock", {})
            lock["hold_s"] = 2.5
            lock["jump_px"] = 190.0
            lock["relock_frames"] = 1
            lock["min_score"] = 0.08
            lock["filter_min_cutoff"] = 0.7
            lock["filter_beta"] = 0.08
        if args.enable_motion:
            with SingleInstanceLock("/tmp/thirdhand-dummy-head-body-follow.lock"):
                asyncio.run(run_loop(cfg, args))
        else:
            asyncio.run(run_loop(cfg, args))
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"[dummy] {exc}", file=sys.stderr, flush=True)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
