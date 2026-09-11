#!/usr/bin/env python3
"""JSON-lines bridge between Node.js and the Startouch Python SDK."""

from __future__ import annotations

import json
import math
import os
import queue
import signal
import socket
import struct
import sys
import tempfile
import threading
import time
from typing import Any

try:
    import fcntl
except ImportError:  # Windows simulator tests do not provide fcntl.
    fcntl = None


SDK_PATH = os.path.expanduser(os.environ.get("STARTOUCH_SDK_PATH", ""))
MODULE_PATH = os.path.expanduser(os.environ.get("STARTOUCH_MODULE_PATH", ""))
CAN_INTERFACE = os.environ.get("STARTOUCH_CAN_INTERFACE", "can0")
SIMULATE = os.environ.get("STARTOUCH_SIMULATE", "0") == "1"
DRY_RUN = os.environ.get("STARTOUCH_DRY_RUN", "0") == "1"
GRIPPER_ENABLED = os.environ.get("STARTOUCH_GRIPPER", "1") != "0"
GRIPPER_MAX_DISTANCE_M = min(
    0.2, max(0.001, float(os.environ.get("STARTOUCH_GRIPPER_MAX_DISTANCE_M", "0.08")))
)
GRIPPER_KP = min(
    20.0, max(0.1, float(os.environ.get("STARTOUCH_GRIPPER_KP", "8.0")))
)
GRIPPER_KD = min(
    1.0, max(0.1, float(os.environ.get("STARTOUCH_GRIPPER_KD", "0.1")))
)
GRIPPER_SETTLE_TIMEOUT_SEC = max(
    0.5, float(os.environ.get("STARTOUCH_GRIPPER_SETTLE_TIMEOUT_SEC", "3.0"))
)
GRIPPER_POSITION_TOLERANCE = min(
    0.25, max(0.005, float(os.environ.get("STARTOUCH_GRIPPER_POSITION_TOLERANCE", "0.03")))
)
GRIPPER_STABLE_SAMPLES = max(
    1, int(os.environ.get("STARTOUCH_GRIPPER_STABLE_SAMPLES", "3"))
)
GRIPPER_LOG_INTERVAL_SEC = max(
    0.1, float(os.environ.get("STARTOUCH_GRIPPER_LOG_INTERVAL_MS", "500")) / 1000
)
REQUIRE_CAN_RX = os.environ.get("STARTOUCH_REQUIRE_CAN_RX", "1") != "0"
CAN_RX_STALE_SEC = max(
    0.25, float(os.environ.get("STARTOUCH_CAN_RX_STALE_SEC", "1.0"))
)
POLL_INTERVAL_SEC = max(0.05, float(os.environ.get("STARTOUCH_POLL_INTERVAL_MS", "100")) / 1000)
JOINT_LOG_INTERVAL_SEC = max(
    0.05, float(os.environ.get("STARTOUCH_JOINT_LOG_INTERVAL_MS", "100")) / 1000
)
INIT_SETTLE_SEC = max(0.0, float(os.environ.get("STARTOUCH_INIT_SETTLE_SEC", "2.0")))
INIT_SAMPLE_COUNT = max(2, int(os.environ.get("STARTOUCH_INIT_SAMPLE_COUNT", "3")))
INIT_MAX_DRIFT_RAD = math.radians(
    max(0.1, float(os.environ.get("STARTOUCH_INIT_MAX_DRIFT_DEG", "2.0")))
)
INIT_CAN_MATCH_RAD = math.radians(
    max(0.1, float(os.environ.get("STARTOUCH_INIT_CAN_MATCH_DEG", "5.0")))
)

JOINT_LIMITS_RAD = [
    (-math.radians(162), math.radians(162)),
    (-math.radians(12), math.radians(201)),
    (-math.radians(183), 0.0),
    (-math.radians(98), math.radians(98)),
    (-math.radians(98), math.radians(98)),
    (-math.radians(164), math.radians(164)),
]

# (joint, ESC_ID, MST_ID, position max, velocity max, torque max)
MOTOR_FEEDBACK_CONFIG = [
    (1, 0x01, 0x11, 12.5, 8.0, 28.0),
    (2, 0x02, 0x12, 12.5, 8.0, 28.0),
    (3, 0x03, 0x13, 12.5, 8.0, 28.0),
    (4, 0x04, 0x14, 12.5, 30.0, 10.0),
    (5, 0x05, 0x15, 12.5, 30.0, 10.0),
    (6, 0x06, 0x16, 12.5, 30.0, 10.0),
]
MOTOR_SIGNS = [1.0, -1.0, -1.0, -1.0, -1.0, 1.0]
CAN_REFRESH_ID = 0x7FF
CAN_REFRESH_OPCODE = 0xCC
CAN_FRAME_FORMAT = "=IB3x8s"
CAN_FRAME_SIZE = struct.calcsize(CAN_FRAME_FORMAT)

_event_lock = threading.Lock()
_event_fd = os.environ.get("STARTOUCH_EVENT_FD")
_event_stream = (
    os.fdopen(int(_event_fd), "w", buffering=1, encoding="utf-8", closefd=False)
    if _event_fd is not None
    else sys.stdout
)


def emit(message_type: str, **payload: Any) -> None:
    message = {"type": message_type, **payload, "ts": int(time.time() * 1000)}
    with _event_lock:
        print(
            json.dumps(message, ensure_ascii=False, separators=(",", ":")),
            file=_event_stream,
            flush=True,
        )


class SimulatedArm:
    def __init__(self) -> None:
        self.joints = [0.0] * 6
        self.gripper = 1.0
        self.stop_event = threading.Event()

    def get_joint_positions(self):
        return self.joints

    def get_joint_velocities(self):
        return [0.0] * 6

    def get_joint_torques(self):
        return [0.0] * 6

    def get_ee_pose_euler(self):
        return ([0.45, 0.0, 0.25], [0.0, 0.0, 0.0])

    def get_gripper_position(self):
        return self.gripper

    def get_gripper_distance(self):
        return self.gripper * GRIPPER_MAX_DISTANCE_M

    def set_joint_waypoints(self, waypoints, time_sec=None, speed_percent=None):
        del speed_percent
        target = list(waypoints[-1])
        duration = max(0.05, float(time_sec or 0.5))
        start = list(self.joints)
        steps = max(1, int(duration / 0.02))
        for step in range(1, steps + 1):
            if self.stop_event.is_set():
                break
            ratio = step / steps
            self.joints = [a + (b - a) * ratio for a, b in zip(start, target)]
            if self.stop_event.wait(duration / steps):
                break
        return duration

    def setGripperPosition(self, position):
        self.gripper = float(position)

    def setGripperDistance(self, distance, kp=None, kd=None):
        del kp, kd
        self.gripper = float(distance) / GRIPPER_MAX_DISTANCE_M

    def cleanup(self):
        self.stop_event.set()


class RobotBridge:
    def __init__(self) -> None:
        self.arm = None
        self.connected = False
        self.state_ready = False
        self.last_valid_joints: list[float] | None = None
        self.motion_active = False
        self.expected_motion_target: list[float] | None = None
        self.stop_requested = threading.Event()
        self.shutdown_requested = threading.Event()
        self.motion_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self.arm_lock = threading.RLock()
        self.control_lock_file = None
        self.last_joint_log_monotonic = 0.0
        self.gripper_target: float | None = None
        self.gripper_start_position: float | None = None
        self.gripper_started_monotonic = 0.0
        self.gripper_stable_samples = 0
        self.last_gripper_log_monotonic = 0.0
        self.can_rx_packets: int | None = None
        self.last_can_rx_monotonic = 0.0
        self.motion_thread = threading.Thread(target=self._motion_loop, daemon=True)
        self.state_thread = threading.Thread(target=self._state_loop, daemon=True)
        self.motion_thread.start()
        self.state_thread.start()

    def _acquire_control_lock(self) -> None:
        if SIMULATE or DRY_RUN or fcntl is None:
            return
        lock_name = f"thirdhand-robot-{CAN_INTERFACE.replace('/', '_')}.lock"
        lock_path = os.path.join(tempfile.gettempdir(), lock_name)
        lock_file = open(lock_path, "a+", encoding="ascii")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock_file.close()
            raise RuntimeError(
                f"{CAN_INTERFACE} is already controlled by another Startouch web process"
            ) from exc
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(f"{os.getpid()}\n")
        lock_file.flush()
        self.control_lock_file = lock_file

    def _release_control_lock(self) -> None:
        lock_file = self.control_lock_file
        self.control_lock_file = None
        if lock_file is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()

    @staticmethod
    def _finite_values(values: Any, count: int, label: str) -> list[float]:
        result = [float(value) for value in values]
        if len(result) != count or not all(math.isfinite(value) for value in result):
            raise RuntimeError(f"{label} did not return {count} finite values")
        return result

    @staticmethod
    def _read_can_rx_packets() -> int | None:
        if SIMULATE or DRY_RUN:
            return None
        stats_path = os.path.join(
            "/sys/class/net",
            CAN_INTERFACE,
            "statistics",
            "rx_packets",
        )
        try:
            with open(stats_path, "r", encoding="ascii") as stats_file:
                return int(stats_file.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _decode_motor_feedback(
        data: bytes,
        *,
        joint: int,
        can_id: int,
        esc_id: int,
        position_max: float,
        velocity_max: float,
        torque_max: float,
    ) -> dict[str, Any]:
        if len(data) < 8:
            raise RuntimeError(f"J{joint} feedback 0x{can_id:03X} is shorter than 8 bytes")
        feedback_id = data[0] & 0x0F
        error_code = data[0] >> 4
        if feedback_id != esc_id:
            raise RuntimeError(
                f"J{joint} feedback ID mismatch: payload={feedback_id}, expected={esc_id}"
            )

        position_raw = (data[1] << 8) | data[2]
        velocity_raw = (data[3] << 4) | (data[4] >> 4)
        torque_raw = ((data[4] & 0x0F) << 8) | data[5]

        def decode(raw: int, limit: float, bits: int) -> float:
            return raw / ((1 << bits) - 1) * (2.0 * limit) - limit

        return {
            "joint": joint,
            "can_id": can_id,
            "feedback_id": feedback_id,
            "error_code": error_code,
            "position_rad": decode(position_raw, position_max, 16),
            "velocity_rad_s": decode(velocity_raw, velocity_max, 12),
            "torque_nm": decode(torque_raw, torque_max, 12),
            "mos_temp_c": data[6],
            "rotor_temp_c": data[7],
            "raw_hex": data.hex().upper(),
        }

    @staticmethod
    def _probe_can_feedback(timeout_sec: float = 1.0) -> list[dict[str, Any]]:
        expected = {config[2]: config for config in MOTOR_FEEDBACK_CONFIG}
        replies: dict[int, dict[str, Any]] = {}
        can_socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            can_socket.bind((CAN_INTERFACE,))
            can_socket.settimeout(0.05)
            for _, esc_id, _, _, _, _ in MOTOR_FEEDBACK_CONFIG:
                payload = struct.pack("<H", esc_id) + bytes([CAN_REFRESH_OPCODE]) + bytes(5)
                frame = struct.pack(
                    CAN_FRAME_FORMAT,
                    CAN_REFRESH_ID,
                    len(payload),
                    payload,
                )
                can_socket.send(frame)
                time.sleep(0.01)

            deadline = time.monotonic() + timeout_sec
            while len(replies) < len(expected) and time.monotonic() < deadline:
                try:
                    raw_frame = can_socket.recv(CAN_FRAME_SIZE)
                except socket.timeout:
                    continue
                if len(raw_frame) != CAN_FRAME_SIZE:
                    continue
                raw_can_id, data_length, data = struct.unpack(
                    CAN_FRAME_FORMAT,
                    raw_frame,
                )
                can_id = raw_can_id & 0x7FF
                config = expected.get(can_id)
                if config is None or data_length < 8:
                    continue
                joint, esc_id, _, position_max, velocity_max, torque_max = config
                replies[can_id] = RobotBridge._decode_motor_feedback(
                    data[:8],
                    joint=joint,
                    can_id=can_id,
                    esc_id=esc_id,
                    position_max=position_max,
                    velocity_max=velocity_max,
                    torque_max=torque_max,
                )
        finally:
            can_socket.close()

        missing = sorted(set(expected) - set(replies))
        if missing:
            missing_text = ", ".join(f"0x{can_id:03X}" for can_id in missing)
            raise RuntimeError(
                f"CAN preflight missing motor feedback on {CAN_INTERFACE}: {missing_text}"
            )
        # 0xD = uncalibrated/unknown position — cleared on enable, not a hard fault
        HARD_FAULTS = {0x8, 0x9, 0xA, 0xB, 0xC, 0xE, 0xF}  # temp, current, etc.
        faults = [reply for reply in replies.values()
                  if reply["error_code"] != 0 and reply["error_code"] != 0x1]
        hard = [r for r in faults if r["error_code"] in HARD_FAULTS]
        soft = [r for r in faults if r["error_code"] not in HARD_FAULTS]
        if soft:
            soft_text = ", ".join(
                f"J{r['joint']}=0x{r['error_code']:X}" for r in soft
            )
            emit("log", level="info",
                 message=f"CAN preflight warnings (will clear on enable): {soft_text}")
        if hard:
            hard_text = ", ".join(
                f"J{r['joint']}=0x{r['error_code']:X}" for r in hard
            )
            raise RuntimeError(f"CAN preflight motor faults: {hard_text}")
        return [replies[config[2]] for config in MOTOR_FEEDBACK_CONFIG]

    def _record_can_rx(self, packets: int | None) -> None:
        self.can_rx_packets = packets
        self.last_can_rx_monotonic = time.monotonic()

    def _can_rx_is_stale(self, packets: int | None) -> bool:
        if not REQUIRE_CAN_RX or SIMULATE or DRY_RUN:
            return False
        if packets is None:
            return True
        if self.can_rx_packets is None or packets > self.can_rx_packets:
            self._record_can_rx(packets)
            return False
        return time.monotonic() - self.last_can_rx_monotonic >= CAN_RX_STALE_SEC

    def _emit_joint_log(
        self,
        joints: list[float],
        phase: str,
        *,
        target: list[float] | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self.last_joint_log_monotonic < JOINT_LOG_INTERVAL_SEC:
            return
        self.last_joint_log_monotonic = now
        emit(
            "joint_log",
            phase=phase,
            joints_rad=list(joints),
            target_joints_rad=list(target) if target is not None else None,
            motion_active=self.motion_active,
        )

    def _read_snapshot(
        self,
        arm: Any,
        *,
        phase: str = "idle",
        force_joint_log: bool = False,
    ) -> dict[str, Any]:
        joints = self._finite_values(arm.get_joint_positions(), 6, "joint positions")
        self._emit_joint_log(joints, phase, force=force_joint_log)
        for index, (value, limits) in enumerate(zip(joints, JOINT_LIMITS_RAD), start=1):
            if value < limits[0] - 0.05 or value > limits[1] + 0.05:
                raise RuntimeError(f"J{index} state is outside the configured joint limit")
        velocities = self._finite_values(arm.get_joint_velocities(), 6, "joint velocities")
        torques = self._finite_values(arm.get_joint_torques(), 6, "joint torques")
        position, euler = arm.get_ee_pose_euler()
        gripper_position = None
        gripper_distance = None
        if GRIPPER_ENABLED:
            gripper_position = float(arm.get_gripper_position())
            gripper_distance = float(arm.get_gripper_distance())
            if not math.isfinite(gripper_position) or not math.isfinite(gripper_distance):
                raise RuntimeError("gripper state contains a non-finite value")
        return {
            "joints": joints,
            "velocities": velocities,
            "torques": torques,
            "position": self._finite_values(position, 3, "TCP position"),
            "euler": self._finite_values(euler, 3, "TCP Euler angles"),
            "gripper": gripper_position,
            "gripper_distance": gripper_distance,
        }

    def _wait_for_stable_state(
        self,
        arm: Any,
        expected_joints: list[float] | None = None,
    ) -> dict[str, Any]:
        samples: list[dict[str, Any]] = []
        settle_sec = 0.0 if SIMULATE or DRY_RUN else INIT_SETTLE_SEC
        interval = settle_sec / max(1, INIT_SAMPLE_COUNT - 1)
        max_attempts = INIT_SAMPLE_COUNT + (2 if expected_joints is not None else 0)
        for attempt in range(max_attempts):
            snapshot = self._read_snapshot(
                arm,
                phase=f"connect_sample_{attempt + 1}",
                force_joint_log=True,
            )
            mismatch = (
                max(
                    abs(actual - expected)
                    for actual, expected in zip(snapshot["joints"], expected_joints)
                )
                if expected_joints is not None
                else 0.0
            )
            if expected_joints is not None and mismatch > INIT_CAN_MATCH_RAD:
                emit(
                    "log",
                    level="warning",
                    message=(
                        f"ignored SDK warmup joint sample {attempt + 1}: "
                        f"max CAN mismatch={math.degrees(mismatch):.2f}deg"
                    ),
                )
            else:
                samples.append(snapshot)
                if len(samples) >= INIT_SAMPLE_COUNT:
                    break
            if attempt + 1 < max_attempts and interval > 0:
                time.sleep(interval)
        if len(samples) < INIT_SAMPLE_COUNT:
            raise RuntimeError(
                "SDK joint state did not converge to the CAN preflight feedback; "
                "motors were disabled"
            )
        for previous, current in zip(samples, samples[1:]):
            drift = max(
                abs(after - before)
                for before, after in zip(previous["joints"], current["joints"])
            )
            if drift > INIT_MAX_DRIFT_RAD:
                raise RuntimeError(
                    "joint state is still moving during SDK initialization; motors were disabled"
                )
        return samples[-1]

    def _emit_snapshot(self, snapshot: dict[str, Any], state: str = "IDLE") -> None:
        emit(
            "robot_state",
            joints_rad=snapshot["joints"],
            velocities_rad_s=snapshot["velocities"],
            torques_nm=snapshot["torques"],
            tcp_position_m=snapshot["position"],
            tcp_euler_rad=snapshot["euler"],
            gripper_position=snapshot["gripper"],
            gripper_distance_m=snapshot["gripper_distance"],
            state=state,
        )

    def _update_gripper_progress_locked(
        self, snapshot: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any] | None]:
        target = self.gripper_target
        actual = snapshot["gripper"]
        if target is None or actual is None:
            return None, None

        now = time.monotonic()
        elapsed = max(0.0, now - self.gripper_started_monotonic)
        error = abs(actual - target)
        if error <= GRIPPER_POSITION_TOLERANCE:
            self.gripper_stable_samples += 1
        else:
            self.gripper_stable_samples = 0

        reached = self.gripper_stable_samples >= GRIPPER_STABLE_SAMPLES
        timed_out = elapsed >= GRIPPER_SETTLE_TIMEOUT_SEC
        should_log = (
            reached
            or timed_out
            or now - self.last_gripper_log_monotonic >= GRIPPER_LOG_INTERVAL_SEC
        )
        log_message = None
        if should_log:
            self.last_gripper_log_monotonic = now
            log_message = (
                f"gripper target={target * 100:.1f}%/"
                f"{target * GRIPPER_MAX_DISTANCE_M * 1000:.1f}mm, "
                f"feedback={actual * 100:.1f}%/"
                f"{snapshot['gripper_distance'] * 1000:.1f}mm, "
                f"error={error * 100:.1f}%, elapsed={elapsed:.2f}s"
            )

        if not reached and not timed_out:
            return log_message, None

        start_position = self.gripper_start_position
        moved = (
            start_position is None
            or abs(actual - start_position) >= GRIPPER_POSITION_TOLERANCE
            or abs(target - start_position) <= GRIPPER_POSITION_TOLERANCE
        )
        result = {
            "command": "gripper",
            "position": target,
            "actual_position": actual,
            "target_distance_m": target * GRIPPER_MAX_DISTANCE_M,
            "actual_distance_m": snapshot["gripper_distance"],
            "reached": reached,
            "moved": moved,
            "elapsed_s": elapsed,
        }
        self.gripper_target = None
        self.gripper_start_position = None
        self.gripper_started_monotonic = 0.0
        self.gripper_stable_samples = 0
        return log_message, result

    def connect(self) -> None:
        if self.connected:
            self.publish_state()
            return

        arm = None
        try:
            self._acquire_control_lock()
            expected_joints = None
            if REQUIRE_CAN_RX and not SIMULATE and not DRY_RUN:
                feedback = self._probe_can_feedback()
                expected_joints = [
                    item["position_rad"] * MOTOR_SIGNS[item["joint"] - 1]
                    for item in feedback
                ]
                feedback_text = ", ".join(
                    (
                        f"J{item['joint']}=0x{item['can_id']:03X}/"
                        f"{math.degrees(item['position_rad']):.2f}deg/"
                        f"{item['mos_temp_c']}C"
                    )
                    for item in feedback
                )
                emit(
                    "log",
                    level="info",
                    message=f"CAN preflight OK: {feedback_text}",
                )
            rx_before = self._read_can_rx_packets()
            emit(
                "log",
                level="info",
                message=(
                    f"constructing SingleArm on {CAN_INTERFACE}; "
                    f"CAN RX before={rx_before}"
                ),
            )
            if SIMULATE:
                arm = SimulatedArm()
            else:
                if not SDK_PATH:
                    raise RuntimeError("STARTOUCH_SDK_PATH is required")
                module_path = MODULE_PATH or os.path.join(SDK_PATH, "interface_py")
                if not os.path.isdir(module_path):
                    raise FileNotFoundError(
                        f"Startouch Python module directory not found: {module_path}"
                    )
                if module_path not in sys.path:
                    sys.path.insert(0, module_path)
                from startouchclass import SingleArm

                arm = SingleArm(
                    can_interface_=CAN_INTERFACE,
                    gripper=GRIPPER_ENABLED,
                    enable_fd_=False,
                    dry_run=DRY_RUN,
                )
                emit(
                    "log",
                    level="info",
                    message="SingleArm constructor returned; sampling joint state",
                )

            snapshot = self._wait_for_stable_state(arm, expected_joints)
            rx_after = self._read_can_rx_packets()
            if (
                REQUIRE_CAN_RX
                and not SIMULATE
                and not DRY_RUN
                and (
                    rx_before is None
                    or rx_after is None
                    or rx_after <= rx_before
                )
            ):
                raise RuntimeError(
                    f"no CAN feedback on {CAN_INTERFACE}: "
                    f"rx_packets {rx_before}->{rx_after}; "
                    "refusing to enable web motion"
                )
            with self.arm_lock:
                self.arm = arm
                self.connected = True
                self.state_ready = True
                self.last_valid_joints = list(snapshot["joints"])
                self.expected_motion_target = None
                self.gripper_target = None
                self.gripper_start_position = None
                self.stop_requested.clear()
                self._record_can_rx(rx_after)
            emit(
                "connection",
                connected=True,
                interface=CAN_INTERFACE,
                sdk_path=SDK_PATH,
                simulated=SIMULATE,
                dry_run=DRY_RUN,
                can_rx_packets=rx_after,
            )
            self._emit_snapshot(snapshot)
        except Exception as exc:
            if arm is not None:
                try:
                    arm.cleanup()
                except Exception:
                    pass
            with self.arm_lock:
                self.arm = None
                self.connected = False
                self.state_ready = False
                self.last_valid_joints = None
                self.expected_motion_target = None
                self.gripper_target = None
                self.gripper_start_position = None
                self.can_rx_packets = None
                self.last_can_rx_monotonic = 0.0
            self._release_control_lock()
            emit(
                "connection",
                connected=False,
                interface=CAN_INTERFACE,
                error=str(exc),
            )

    def disconnect(self, reason: str = "requested") -> None:
        self.stop_requested.set()
        with self.arm_lock:
            arm = self.arm
            self.arm = None
            self.connected = False
            self.state_ready = False
            self.last_valid_joints = None
            self.expected_motion_target = None
            self.gripper_target = None
            self.gripper_start_position = None
            self.can_rx_packets = None
            self.last_can_rx_monotonic = 0.0
        while True:
            try:
                self.motion_queue.get_nowait()
            except queue.Empty:
                break
        if arm is not None:
            try:
                arm.cleanup()
            except Exception as exc:
                emit("log", level="warning", message=f"SDK cleanup failed: {exc}")
        self._release_control_lock()
        emit("connection", connected=False, interface=CAN_INTERFACE, reason=reason)

    def enqueue_motion(self, command: dict[str, Any]) -> None:
        with self.arm_lock:
            connected = self.connected
            state_ready = self.state_ready
            motion_active = self.motion_active
            start_joints = (
                list(self.last_valid_joints) if self.last_valid_joints is not None else None
            )
        if not connected:
            emit("error", message="Startouch SDK is not connected")
            return
        if not state_ready or start_joints is None:
            emit("error", message="robot state is not ready; motion command was rejected")
            return
        if motion_active or not self.motion_queue.empty():
            emit("error", message="a joint motion is already active")
            return

        command_name = str(command.get("cmd", "move_joint"))
        if command_name == "move_joint_path":
            raw_waypoints = command.get("waypoints_rad")
            if not isinstance(raw_waypoints, list) or not raw_waypoints:
                emit("error", message="waypoints_rad must contain at least one waypoint")
                return
        else:
            raw_waypoints = [command.get("joints_rad")]
        waypoints: list[list[float]] = []
        for point_index, joints in enumerate(raw_waypoints, start=1):
            if not isinstance(joints, list) or len(joints) != 6:
                emit(
                    "error",
                    message=f"waypoint {point_index} must contain six values",
                )
                return
            try:
                point = [float(value) for value in joints]
            except (TypeError, ValueError):
                emit(
                    "error",
                    message=f"waypoint {point_index} contains a non-numeric value",
                )
                return
            if not all(math.isfinite(value) for value in point):
                emit(
                    "error",
                    message=f"waypoint {point_index} contains a non-finite value",
                )
                return
            for joint_index, (value, limits) in enumerate(
                zip(point, JOINT_LIMITS_RAD),
                start=1,
            ):
                if value < limits[0] or value > limits[1]:
                    emit(
                        "error",
                        message=(
                            f"waypoint {point_index} J{joint_index} is outside "
                            "the Startouch joint limit"
                        ),
                    )
                    return
            waypoints.append(point)
        target = waypoints[-1]

        source = str(command.get("source", "servo"))
        if (
            source != "preset:home"
            and max(abs(value) for value in target) < math.radians(0.05)
            and max(abs(value) for value in start_joints) > math.radians(2.0)
        ):
            emit(
                "error",
                message="all-zero target rejected; use the explicit home control",
            )
            return

        item = {
            "start_joints_rad": start_joints,
            "joints_rad": target,
            "waypoints_rad": waypoints,
            "time_sec": max(0.2, min(30.0, float(command.get("time_sec", 2.0)))),
            "request_id": command.get("request_id"),
            "source": source,
            "command": command_name,
        }
        self.motion_queue.put_nowait(item)
        self._emit_joint_log(
            start_joints,
            "command_queued",
            target=target,
            force=True,
        )
        emit(
            "command_accepted",
            command=command_name,
            request_id=item["request_id"],
            source=source,
        )

    def set_gripper(
        self,
        position: Any,
        kp: Any = None,
        kd: Any = None,
    ) -> None:
        if not self.connected or self.arm is None:
            emit("error", message="Startouch SDK is not connected")
            return
        if self.motion_active:
            emit("error", message="gripper command rejected while joint motion is active")
            return
        try:
            value = float(position)
        except (TypeError, ValueError):
            emit("error", message="gripper position must be numeric")
            return
        if not math.isfinite(value) or value < 0.0 or value > 1.0:
            emit("error", message="gripper position must be between 0 and 1")
            return
        try:
            kp_value = GRIPPER_KP if kp is None else float(kp)
            kd_value = GRIPPER_KD if kd is None else float(kd)
        except (TypeError, ValueError):
            emit("error", message="gripper kp/kd must be numeric")
            return
        if (
            not math.isfinite(kp_value)
            or not 0.1 <= kp_value <= 20.0
            or not math.isfinite(kd_value)
            or not 0.1 <= kd_value <= 1.0
        ):
            emit("error", message="gripper kp/kd is outside the safe SDK range")
            return
        try:
            with self.arm_lock:
                before_position = float(self.arm.get_gripper_position())
                before_distance = float(self.arm.get_gripper_distance())
                target_distance = value * GRIPPER_MAX_DISTANCE_M
                self.arm.setGripperDistance(target_distance, kp_value, kd_value)
                self.gripper_target = value
                self.gripper_start_position = before_position
                self.gripper_started_monotonic = time.monotonic()
                self.gripper_stable_samples = 0
                self.last_gripper_log_monotonic = 0.0
            emit(
                "log",
                level="info",
                message=(
                    f"gripper command target={value * 100:.1f}%/"
                    f"{target_distance * 1000:.1f}mm, "
                    f"before={before_position * 100:.1f}%/"
                    f"{before_distance * 1000:.1f}mm, "
                    f"kp={kp_value:g}, kd={kd_value:g}"
                ),
            )
            emit("command_accepted", command="gripper", position=value)
        except Exception as exc:
            emit("error", message=f"gripper command failed: {exc}")

    def move_linear(self, command: dict[str, Any]) -> None:
        """Execute a Cartesian linear move (move_l)."""
        with self.arm_lock:
            connected = self.connected
            state_ready = self.state_ready
            motion_active = self.motion_active
        if not connected:
            emit("error", message="Startouch SDK is not connected")
            return
        if not state_ready:
            emit("error", message="robot state is not ready; motion command was rejected")
            return
        if motion_active or not self.motion_queue.empty():
            emit("error", message="a motion is already active")
            return

        position = command.get("position")
        euler = command.get("euler")
        time_sec = float(command.get("time_sec", 2.0))
        request_id = command.get("request_id")

        if not isinstance(position, list) or len(position) != 3:
            emit("error", message="move_l position must contain three values")
            return
        if not isinstance(euler, list) or len(euler) != 3:
            emit("error", message="move_l euler must contain three values")
            return
        try:
            pos = [float(v) for v in position]
            rot = [float(v) for v in euler]
        except (TypeError, ValueError):
            emit("error", message="move_l position/euler contain non-numeric values")
            return
        if not all(math.isfinite(v) for v in pos + rot):
            emit("error", message="move_l position/euler contain non-finite values")
            return

        time_sec = max(0.2, min(30.0, time_sec))
        # Use a fake joint target so enqueue_motion doesn't reject it
        fake_item = {
            "start_joints_rad": self.last_valid_joints or [0.0] * 6,
            "joints_rad": self.last_valid_joints or [0.0] * 6,
            "waypoints_rad": [self.last_valid_joints or [0.0] * 6],
            "time_sec": time_sec,
            "request_id": request_id,
            "source": "move_l",
            "command": "move_l",
            "_move_l_pos": pos,
            "_move_l_euler": rot,
        }
        self.motion_queue.put_nowait(fake_item)
        emit("command_accepted", command="move_l", request_id=request_id, source="move_l")

    def go_home(self, request_id: str | None = None) -> None:
        """Send the arm to its home position."""
        with self.arm_lock:
            connected = self.connected
            state_ready = self.state_ready
            motion_active = self.motion_active
        if not connected:
            emit("error", message="Startouch SDK is not connected")
            return
        if not state_ready:
            emit("error", message="robot state is not ready; motion command was rejected")
            return
        if motion_active or not self.motion_queue.empty():
            emit("error", message="a motion is already active")
            return

        fake_item = {
            "start_joints_rad": self.last_valid_joints or [0.0] * 6,
            "joints_rad": [0.0] * 6,
            "waypoints_rad": [[0.0] * 6],
            "time_sec": 5.0,
            "request_id": request_id,
            "source": "go_home",
            "command": "go_home",
            "_go_home": True,
        }
        self.motion_queue.put_nowait(fake_item)
        emit("command_accepted", command="go_home", request_id=request_id, source="go_home")

    def publish_state(
        self,
        *,
        phase: str = "idle",
        force_joint_log: bool = False,
    ) -> None:
        stale_can_rx = False
        rx_packets = None
        try:
            gripper_log = None
            gripper_result = None
            with self.arm_lock:
                if (
                    not self.connected
                    or self.arm is None
                    or self.motion_active
                ):
                    return
                snapshot = self._read_snapshot(
                    self.arm,
                    phase=phase,
                    force_joint_log=force_joint_log,
                )
                if (
                    self.last_valid_joints is not None
                    and max(abs(value) for value in snapshot["joints"]) < math.radians(0.05)
                    and max(abs(value) for value in self.last_valid_joints) > math.radians(2.0)
                ):
                    self.state_ready = False
                    raise RuntimeError(
                        "SDK returned a transient all-zero joint cache; sample ignored"
                    )
                self.last_valid_joints = list(snapshot["joints"])
                self.state_ready = True
                rx_packets = self._read_can_rx_packets()
                stale_can_rx = self._can_rx_is_stale(rx_packets)
                if stale_can_rx:
                    self.state_ready = False
                gripper_log, gripper_result = self._update_gripper_progress_locked(snapshot)
            if stale_can_rx:
                emit(
                    "error",
                    message=(
                        f"CAN feedback stopped on {CAN_INTERFACE}: "
                        f"rx_packets={rx_packets}; disconnecting SDK"
                    ),
                )
                self.disconnect("can_rx_stale")
                return
            self._emit_snapshot(snapshot)
            if gripper_log is not None:
                emit(
                    "log",
                    level=(
                        "warning"
                        if gripper_result is not None and not gripper_result["reached"]
                        else "info"
                    ),
                    message=gripper_log,
                )
            if gripper_result is not None:
                emit("command_complete", **gripper_result)
        except Exception as exc:
            with self.arm_lock:
                self.state_ready = False
            emit("error", message=f"failed to read robot state: {exc}")

    def _motion_loop(self) -> None:
        while not self.shutdown_requested.is_set():
            try:
                command = self.motion_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.stop_requested.is_set() or not self.connected or self.arm is None:
                continue

            with self.arm_lock:
                self.motion_active = True
                self.expected_motion_target = list(command["joints_rad"])
            self._emit_joint_log(
                command["start_joints_rad"],
                "motion_start",
                target=command["joints_rad"],
                force=True,
            )
            emit("motion_state", state="MOVING", request_id=command["request_id"])
            try:
                with self.arm_lock:
                    arm = self.arm
                if arm is None:
                    continue

                if command.get("_go_home"):
                    # go_home path
                    if hasattr(arm, 'go_home'):
                        arm.go_home()
                    else:
                        arm.set_joint_waypoints(
                            [command["start_joints_rad"], [0.0] * 6],
                            time_sec=5.0,
                        )
                    # After homing, read actual joint state
                    try:
                        joints = self._finite_values(arm.get_joint_positions(), 6, "joint positions after home")
                        with self.arm_lock:
                            self.last_valid_joints = list(joints)
                    except Exception:
                        with self.arm_lock:
                            self.last_valid_joints = [0.0] * 6
                    if not self.stop_requested.is_set():
                        emit(
                            "command_complete",
                            command="go_home",
                            duration_sec=5.0,
                            request_id=command["request_id"],
                        )
                elif command.get("_move_l_pos"):
                    # move_l Cartesian path
                    pos = command["_move_l_pos"]
                    euler = command["_move_l_euler"]
                    time_sec = command["time_sec"]
                    arm.move_l(
                        [[pos[0], pos[1], pos[2], euler[0], euler[1], euler[2]]],
                        time_sec=time_sec,
                        blend_radius_m=0.0,
                        position_tolerance_m=0.04,
                        orientation_tolerance_rad=0.4,
                    )
                    # After move, read actual joint state
                    try:
                        joints = self._finite_values(arm.get_joint_positions(), 6, "joint positions after move_l")
                        with self.arm_lock:
                            self.last_valid_joints = list(joints)
                    except Exception:
                        pass
                    if not self.stop_requested.is_set():
                        emit(
                            "command_complete",
                            command="move_l",
                            duration_sec=float(time_sec),
                            request_id=command["request_id"],
                        )
                else:
                    # Joint waypoints path (existing)
                    duration = arm.set_joint_waypoints(
                        [command["start_joints_rad"], *command["waypoints_rad"]],
                        time_sec=command["time_sec"],
                    )
                    if not self.stop_requested.is_set():
                        with self.arm_lock:
                            self.last_valid_joints = list(command["joints_rad"])
                        emit(
                            "command_complete",
                            command=command["command"],
                            duration_sec=float(duration),
                            request_id=command["request_id"],
                        )
            except Exception as exc:
                emit("error", message=f"joint motion failed: {exc}", request_id=command["request_id"])
            finally:
                with self.arm_lock:
                    self.motion_active = False
                    self.expected_motion_target = None
                    still_connected = self.connected
                if still_connected:
                    emit("motion_state", state="IDLE", request_id=command["request_id"])
                    self.publish_state(
                        phase="motion_complete",
                        force_joint_log=True,
                    )

    def _state_loop(self) -> None:
        while not self.shutdown_requested.wait(POLL_INTERVAL_SEC):
            self.publish_state()

    def shutdown(self) -> None:
        self.shutdown_requested.set()
        self.disconnect("bridge_shutdown")


def main() -> None:
    bridge = RobotBridge()

    def request_shutdown(_signum=None, _frame=None):
        bridge.shutdown()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)
    emit(
        "bridge_ready",
        interface=CAN_INTERFACE,
        sdk_path=SDK_PATH,
        simulated=SIMULATE,
        dry_run=DRY_RUN,
    )

    for line in sys.stdin:
        if bridge.shutdown_requested.is_set():
            break
        try:
            command = json.loads(line)
            name = command.get("cmd")
            if name == "connect":
                bridge.connect()
            elif name == "disconnect":
                bridge.disconnect(str(command.get("reason", "requested")))
            elif name == "software_stop":
                bridge.disconnect("software_stop")
            elif name in {"move_joint", "move_joint_path"}:
                bridge.enqueue_motion(command)
            elif name == "move_l":
                bridge.move_linear(command)
            elif name == "go_home":
                bridge.go_home(command.get("request_id"))
            elif name == "gripper":
                bridge.set_gripper(
                    command.get("position"),
                    command.get("kp"),
                    command.get("kd"),
                )
            elif name == "get_state":
                if bridge.connected:
                    bridge.publish_state()
                else:
                    emit("error", message="Startouch SDK is not connected")
            elif name == "shutdown":
                bridge.shutdown()
                break
            else:
                emit("error", message=f"unknown bridge command: {name}")
        except json.JSONDecodeError as exc:
            emit("error", message=f"invalid bridge JSON: {exc}")
        except Exception as exc:
            emit("error", message=f"bridge command failed: {exc}")


if __name__ == "__main__":
    main()
