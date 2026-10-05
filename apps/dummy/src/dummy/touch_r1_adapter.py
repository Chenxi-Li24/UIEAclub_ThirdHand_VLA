from __future__ import annotations

import asyncio
import math
import time
from uuid import uuid4

from .robot_ws_client import RobotWebSocketClient
from .workspace_guard import WorkspaceGuard


class TouchR1Adapter:
    def __init__(self, config: dict, *, workspace_guard=None):
        robot = config.get("robot", {})
        self.client = RobotWebSocketClient(
            robot.get("ws_url", "ws://127.0.0.1:3000/ws"),
            robot.get("health_url", "http://127.0.0.1:3000/health"),
        )
        self.joint_limits = robot.get(
            "joint_limits_deg",
            [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        )
        self.max_speed_deg_s = float(robot.get("max_speed_deg_s", 10.0))
        if not math.isfinite(self.max_speed_deg_s) or self.max_speed_deg_s <= 0:
            raise ValueError("robot max speed must be finite and positive")
        self.min_command_interval = float(robot.get("min_command_interval_s", 0.10))
        self.servo_min_time_sec = float(robot.get("servo_min_time_sec", 0.20))
        self.follow_command = str(robot.get("follow_command", "move_joint") or "move_joint")
        self.follow_wait_complete = bool(robot.get("follow_wait_complete", True))
        self.follow_ack_timeout = float(robot.get("follow_ack_timeout_s", 1.0))
        self.home_joints = robot.get("home_joints_deg")
        self.home_preset_name = str(robot.get("home_preset_name", "zero") or "zero")
        self.workspace_guard = workspace_guard if workspace_guard is not None else WorkspaceGuard(config)
        self._last_send = 0.0
        self.last_request_id = None
        self._inflight = None

    async def connect(self):
        await self.client.open()
        health = await asyncio.to_thread(self.client.health)
        if not health.get("robot", {}).get("connected"):
            return await self.client.connect_robot()
        await self.client.command("status")
        return await self.client.wait_state()

    async def disconnect(self):
        try:
            await self.client.command("disconnect")
        finally:
            await self.client.close()

    async def go_home(self):
        await self.client.open()
        if self.home_joints and any(abs(float(joint)) > 1e-9 for joint in self.home_joints):
            state = await self.get_state()
            start = list(state.joints_deg)
            target = self._validate(self.home_joints)
            if len(start) == 6:
                await self.send_joint_target(target, allow_large=True)
                await self.wait_idle(timeout=35.0)
                return await self.get_state()
        if self.home_preset_name != "zero":
            raise ValueError("speed-limited home requires zero or explicit home_joints_deg")
        state = await self.get_state()
        duration = self._time_for_speed_limit([0.0] * 6, state.joints_deg)
        if duration > 30.0:
            raise ValueError("speed-limited home exceeds Robot Service's 30 second duration limit")
        await self.client.command("preset", name="zero", time_sec=duration)
        return await self.wait_idle(timeout=35.0)

    async def close(self):
        try:
            if self._inflight is not None:
                # Cancellation of Dummy must not orphan its completion waiter.
                await asyncio.shield(self._inflight)
        finally:
            self._inflight = None
            await self.client.close()

    async def get_state(self):
        state = await self.client.refresh_state(timeout=2.0)
        if not state.connected or not state.state_ready or len(state.joints_deg) != 6:
            raise RuntimeError("fresh valid robot feedback is unavailable")
        return state

    def latest_state(self):
        return self.client.snapshot

    async def get_joint_positions(self):
        return (await self.get_state()).joints_deg

    async def get_joint_velocities(self):
        return (await self.get_state()).velocities_deg_s

    async def get_tcp_pose(self):
        state = await self.get_state()
        return {"position_mm": state.tcp_pos_mm, "euler_deg": state.tcp_euler_deg}

    async def get_gripper_state(self):
        state = await self.get_state()
        return {"position": state.gripper_position, "distance_mm": state.gripper_distance_mm}

    def _validate(self, joints):
        if len(joints) != 6:
            raise ValueError("joint target must contain six degree values")
        out = [float(x) for x in joints]
        for index, (value, (lo, hi)) in enumerate(zip(out, self.joint_limits), start=1):
            if not math.isfinite(value):
                raise ValueError(f"J{index} target must be finite")
            if value < lo - 0.05 or value > hi + 0.05:
                raise ValueError(f"J{index} target {value:.3f} outside limit [{lo},{hi}]")
            out[index - 1] = min(max(value, lo), hi)
        return out

    async def send_joint_target(self, joints_deg, *, allow_large=False, time_sec=None, skip_if_busy=False, before_send=None):
        if self.client.snapshot.moving or self.client.snapshot.state_name == "MOVING":
            if skip_if_busy:
                return False
            await self.wait_idle()
        target = self._validate(joints_deg)
        state = await self.get_state()
        if state.moving or state.state_name == "MOVING":
            return False
        elapsed = time.monotonic() - self._last_send
        if elapsed < self.min_command_interval:
            await asyncio.sleep(self.min_command_interval - elapsed)
            state = await self.get_state()
            if state.moving:
                return False
        if before_send is not None:
            latest_target = before_send(state)
            if latest_target is None:
                return False
            target = self._validate(latest_target)
        if not allow_large:
            allowed, reason = self.workspace_guard.check(target)
            if not allowed:
                raise RuntimeError(f"workspace guard rejected target: {reason}")
        required_time = self._time_for_speed_limit(target, state.joints_deg)
        if time_sec is None:
            time_sec = required_time
        else:
            time_sec = float(time_sec)
            if not math.isfinite(time_sec) or time_sec <= 0:
                raise ValueError("motion duration must be finite and positive")
            time_sec = max(required_time, time_sec)
        if time_sec > 30.0:
            raise ValueError("speed-limited motion exceeds Robot Service's 30 second duration limit")
        request_id = f"dummy-follow-{uuid4()}"
        self.last_request_id = request_id
        if not self.follow_wait_complete:
            if self.follow_command == "servo":
                await self.client.command("servo", joints=target, time_sec=time_sec, request_id=request_id)
            else:
                await self.client.command(
                    "move_joint",
                    joints_deg=target,
                    time_sec=max(self.servo_min_time_sec, float(time_sec)),
                    source="dummy_follow",
                    request_id=request_id,
                )
            self._last_send = time.monotonic()
            return True
        if self.follow_command == "servo":
            waiter = self.client.command_wait(
                "servo",
                joints=target,
                time_sec=time_sec,
                request_id=request_id,
                timeout=max(self.follow_ack_timeout, float(time_sec) + 1.0),
                terminal_only=self.follow_wait_complete,
            )
        else:
            waiter = self.client.command_wait(
                "move_joint",
                joints_deg=target,
                time_sec=max(self.servo_min_time_sec, float(time_sec)),
                source="dummy_follow",
                request_id=request_id,
                timeout=max(self.follow_ack_timeout, float(time_sec) + 1.0) if self.follow_wait_complete else self.follow_ack_timeout,
                terminal_only=self.follow_wait_complete,
            )
        self._inflight = asyncio.create_task(waiter)
        try:
            ack = await asyncio.shield(self._inflight)
        finally:
            if self._inflight.done():
                self._inflight = None
        if ack is None:
            raise RuntimeError(f"robot command timed out waiting for request_id={request_id}")
        if isinstance(ack, dict) and ack.get("type") == "error":
            raise RuntimeError(f"robot command rejected: {ack.get('code', '-')}: {ack.get('msg', ack)}")
        if isinstance(ack, dict) and ack.get("status") in {"failed", "rejected", "uncertain"}:
            raise RuntimeError(f"robot command {ack['status']}: {ack.get('msg', ack)}")
        if ack.get("reached") is False:
            raise RuntimeError("robot command completed without reaching its target")
        self._last_send = time.monotonic()
        return True

    def _time_for_speed_limit(self, target, current):
        if not current or len(current) != 6 or not all(math.isfinite(float(value)) for value in current):
            raise ValueError("speed-limited motion requires six finite measured joints")
        delta = max(abs(float(dst) - float(src)) for dst, src in zip(target, current))
        # A zero-endpoint-velocity quintic peaks at 1.875 * delta / duration.
        # Use 2.0 conservatively; do not mistake average speed for peak speed.
        return max(self.servo_min_time_sec, 2.0 * delta / self.max_speed_deg_s)

    async def set_gripper(self, position):
        if self.client.snapshot.moving or self.client.snapshot.state_name == "MOVING":
            await self.wait_idle()
        value = float(position)
        if not math.isfinite(value) or value < 0 or value > 1:
            raise ValueError("gripper position must be 0..1")
        await self.client.command("gripper", position=value)

    async def software_stop(self):
        await self.client.command("software_stop")

    async def wait_idle(self, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            state = await self.get_state()
            if state.state_ready and not state.moving and state.state_name != "MOVING":
                return state
            await asyncio.sleep(0.15)
        raise TimeoutError("robot did not become idle")
