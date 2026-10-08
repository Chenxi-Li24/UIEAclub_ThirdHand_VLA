from __future__ import annotations

import asyncio
import math
import time
from uuid import uuid4

from .robot_ws_client import RobotWebSocketClient
from .filters import clamp
from .workspace_guard import WorkspaceGuard


class TouchR1Adapter:
    def __init__(self, config: dict):
        robot = config.get("robot", {})
        self.client = RobotWebSocketClient(
            robot.get("ws_url", "ws://127.0.0.1:3000/ws"),
            robot.get("health_url", "http://127.0.0.1:3000/health"),
        )
        self.joint_limits = robot.get(
            "joint_limits_deg",
            [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
        )
        self.max_delta = float(robot.get("max_relative_move_deg", 1.0))
        self.min_command_interval = float(robot.get("min_command_interval_s", 0.10))
        self.follow_speed_percent = float(robot.get("follow_speed_percent", 0.05))
        self.servo_min_time_sec = float(robot.get("servo_min_time_sec", 0.20))
        self.follow_command = str(robot.get("follow_command", "move_joint") or "move_joint")
        self.follow_wait_complete = bool(robot.get("follow_wait_complete", True))
        self.follow_ack_timeout = float(robot.get("follow_ack_timeout_s", 1.0))
        self.servo_max_speeds_deg_s = [
            float(x) for x in robot.get("servo_max_speeds_deg_s", [300, 300, 300, 1000, 1000, 1000])
        ]
        self.home_joints = robot.get("home_joints_deg")
        self.home_preset_name = str(robot.get("home_preset_name", "zero") or "zero")
        self.workspace_guard = WorkspaceGuard(config)
        self._last_send = 0.0

    async def connect(self):
        await self.client.open()
        health = self.client.health()
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
                max_delta = max(abs(a - b) for a, b in zip(target, start))
                steps = max(1, math.ceil(max_delta / max(self.max_delta * 0.8, 0.1)))
                for step in range(1, steps + 1):
                    alpha = step / steps
                    waypoint = [a + (b - a) * alpha for a, b in zip(start, target)]
                    await self.send_joint_target(waypoint, allow_large=True)
                    await self.wait_idle(timeout=20.0)
                return await self.get_state()
        await self.client.command("preset", name=self.home_preset_name)
        return await self.wait_idle(timeout=20.0)

    async def close(self):
        await self.client.close()

    async def get_state(self):
        try:
            return await self.client.refresh_state(timeout=2.0)
        except Exception:
            return self.client.snapshot

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
            if value < lo - 0.05 or value > hi + 0.05:
                raise ValueError(f"J{index} target {value:.3f} outside limit [{lo},{hi}]")
            out[index - 1] = min(max(value, lo), hi)
        return out

    async def send_joint_target(self, joints_deg, *, allow_large=False, time_sec=None, skip_if_busy=False):
        if self.client.snapshot.moving or self.client.snapshot.state_name == "MOVING":
            if skip_if_busy:
                return False
            await self.wait_idle()
        target = self._validate(joints_deg)
        state = await self.get_state()
        if skip_if_busy and (state.moving or state.state_name == "MOVING"):
            return False
        if state.joints_deg and not allow_large and self.max_delta > 0.0:
            delta = max(abs(a - b) for a, b in zip(target, state.joints_deg))
            if delta > self.max_delta:
                target = self._clamp_relative_step(state.joints_deg, target)
        if not allow_large:
            allowed, reason = self.workspace_guard.check(target)
            if not allowed:
                raise RuntimeError(f"workspace guard rejected target: {reason}")
        elapsed = time.time() - self._last_send
        if elapsed < self.min_command_interval:
            await asyncio.sleep(self.min_command_interval - elapsed)
        if time_sec is None:
            time_sec = self._time_for_speed_percent(target, state.joints_deg)
        request_id = f"dummy-follow-{uuid4()}"
        if not self.follow_wait_complete:
            if self.follow_command == "servo":
                await self.client.command("servo", joints=target, request_id=request_id)
            else:
                await self.client.command(
                    "move_joint",
                    joints_deg=target,
                    time_sec=max(self.servo_min_time_sec, float(time_sec)),
                    source="dummy_follow",
                    request_id=request_id,
                )
            self._last_send = time.time()
            return True
        if self.follow_command == "servo":
            ack = await self.client.command_wait(
                "servo",
                joints=target,
                request_id=request_id,
                timeout=self.follow_ack_timeout,
                terminal_only=self.follow_wait_complete,
            )
        else:
            ack = await self.client.command_wait(
                "move_joint",
                joints_deg=target,
                time_sec=max(self.servo_min_time_sec, float(time_sec)),
                source="dummy_follow",
                request_id=request_id,
                timeout=max(self.follow_ack_timeout, float(time_sec) + 1.0) if self.follow_wait_complete else self.follow_ack_timeout,
                terminal_only=self.follow_wait_complete,
            )
        if ack is None:
            raise RuntimeError(f"robot command timed out waiting for request_id={request_id}")
        if isinstance(ack, dict) and ack.get("type") == "error":
            raise RuntimeError(f"robot command rejected: {ack.get('code', '-')}: {ack.get('msg', ack)}")
        self._last_send = time.time()
        return True

    def _clamp_relative_step(self, current, target):
        out = []
        for src, dst in zip(current, target):
            src = float(src)
            dst = float(dst)
            out.append(src + clamp(dst - src, -self.max_delta, self.max_delta))
        return out

    def _time_for_speed_percent(self, target, current):
        if not current or len(current) != 6:
            return self.servo_min_time_sec
        speed = max(0.01, min(1.0, self.follow_speed_percent))
        durations = []
        for index, (dst, src) in enumerate(zip(target, current)):
            max_speed = self.servo_max_speeds_deg_s[index] if index < len(self.servo_max_speeds_deg_s) else 300.0
            durations.append(abs(float(dst) - float(src)) / max(1e-6, max_speed * speed))
        return max(self.servo_min_time_sec, max(durations or [0.0]))

    async def set_gripper(self, position):
        if self.client.snapshot.moving or self.client.snapshot.state_name == "MOVING":
            await self.wait_idle()
        value = float(position)
        if value < 0 or value > 1:
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
