from __future__ import annotations

import asyncio
import math
import time

from .robot_ws_client import RobotWebSocketClient


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
        self.follow_speed_percent = float(robot.get("follow_speed_percent", 0.50))
        self.servo_min_time_sec = float(robot.get("servo_min_time_sec", 0.20))
        self.servo_max_speeds_deg_s = [
            float(x) for x in robot.get("servo_max_speeds_deg_s", [300, 300, 300, 1000, 1000, 1000])
        ]
        self.home_joints = robot.get("home_joints_deg")
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
        await self.client.command("preset", name="home")
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

    async def send_joint_target(self, joints_deg, *, allow_large=False, time_sec=None):
        if self.client.snapshot.moving or self.client.snapshot.state_name == "MOVING":
            await self.wait_idle()
        target = self._validate(joints_deg)
        state = await self.get_state()
        if state.joints_deg and not allow_large:
            delta = max(abs(a - b) for a, b in zip(target, state.joints_deg))
            if delta > self.max_delta:
                raise ValueError(f"relative move {delta:.3f} deg exceeds {self.max_delta:.3f} deg")
        elapsed = time.time() - self._last_send
        if elapsed < self.min_command_interval:
            await asyncio.sleep(self.min_command_interval - elapsed)
        if time_sec is None:
            time_sec = self._time_for_speed_percent(target, state.joints_deg)
        # The robot service's legacy ``servo`` route ignores ``time_sec`` and
        # falls back to its global speed scale.  ``move_joint`` carries the
        # requested duration through to the Startouch bridge, so the configured
        # follow speed is actually applied by the hardware.
        await self.client.command(
            "move_joint",
            joints_deg=target,
            time_sec=float(time_sec),
            source="dummy_follow",
        )
        self._last_send = time.time()

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
