from __future__ import annotations

import asyncio
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import websockets


@dataclass
class RobotSnapshot:
    connected: bool = False
    state_ready: bool = False
    moving: bool = False
    joints_deg: list[float] = field(default_factory=list)
    velocities_deg_s: list[float] = field(default_factory=list)
    torques_nm: list[float] = field(default_factory=list)
    tcp_pos_mm: list[float] = field(default_factory=list)
    tcp_euler_deg: list[float] = field(default_factory=list)
    gripper_position: float | None = None
    gripper_distance_mm: float | None = None
    state_name: str | None = None
    ts: float | None = None
    last_event_at: float = 0.0


class RobotWebSocketClient:
    def __init__(
        self,
        url="ws://127.0.0.1:3000/ws",
        health_url="http://127.0.0.1:3000/health",
        timeout=5.0,
    ):
        self.url = url
        self.health_url = health_url
        self.timeout = timeout
        self.ws = None
        self.reader_task = None
        self.snapshot = RobotSnapshot()
        self.events = []
        self.listeners = []
        self._state_event = asyncio.Event()

    def health(self):
        with urllib.request.urlopen(self.health_url, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def open(self):
        if self.ws:
            return
        self.ws = await websockets.connect(self.url, open_timeout=self.timeout)
        self.reader_task = asyncio.create_task(self._reader())

    async def close(self):
        if self.ws:
            await self.ws.close()
        if self.reader_task:
            try:
                await asyncio.wait_for(self.reader_task, timeout=1.0)
            except Exception:
                self.reader_task.cancel()
        self.ws = None
        self.reader_task = None

    async def _reader(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                self.events.append(msg)
                self.events = self.events[-200:]
                self._apply(msg)
                for cb in list(self.listeners):
                    try:
                        cb(msg)
                    except Exception:
                        pass
        finally:
            self.snapshot.connected = False

    def _apply(self, msg):
        typ = msg.get("type")
        now = time.time()
        if typ == "connection":
            self.snapshot.connected = bool(msg.get("connected"))
            self.snapshot.state_ready = False
            self.snapshot.last_event_at = now
        elif typ == "robot_state":
            joints = [float(x) for x in msg.get("joints", []) if isinstance(x, (int, float))]
            vels = [float(x) for x in msg.get("velocities", []) if isinstance(x, (int, float))]
            self.snapshot.joints_deg = joints
            self.snapshot.velocities_deg_s = vels
            self.snapshot.torques_nm = [float(x) for x in msg.get("torques", []) if isinstance(x, (int, float))]
            self.snapshot.tcp_pos_mm = [float(x) for x in msg.get("tcpPos", []) if isinstance(x, (int, float))]
            self.snapshot.tcp_euler_deg = [float(x) for x in msg.get("tcpEuler", []) if isinstance(x, (int, float))]
            self.snapshot.gripper_position = msg.get("gripperPosition")
            self.snapshot.gripper_distance_mm = msg.get("gripperDistanceMm")
            self.snapshot.state_name = msg.get("stateName")
            self.snapshot.ts = msg.get("ts")
            self.snapshot.state_ready = len(joints) == 6
            self.snapshot.moving = self.snapshot.state_name == "MOVING"
            self.snapshot.connected = True
            self.snapshot.last_event_at = now
            self._state_event.set()
        elif typ == "motion_state":
            self.snapshot.state_name = msg.get("stateName")
            self.snapshot.moving = self.snapshot.state_name == "MOVING"

    async def command(self, cmd, **kwargs):
        payload = json.dumps({"cmd": cmd, **kwargs}, separators=(",", ":"))
        try:
            await self.open()
            await self.ws.send(payload)
        except Exception:
            await self.close()
            await self.open()
            await self.ws.send(payload)

    async def wait_state(self, timeout=5.0):
        if self.snapshot.state_ready:
            return self.snapshot
        self._state_event.clear()
        await asyncio.wait_for(self._state_event.wait(), timeout=timeout)
        return self.snapshot

    async def refresh_state(self, timeout=2.0):
        """Request and wait for a state message newer than this call."""

        await self.open()
        self._state_event.clear()
        await self.command("status")
        await asyncio.wait_for(self._state_event.wait(), timeout=timeout)
        return self.snapshot

    async def connect_robot(self, timeout=10.0):
        await self.open()
        await self.command("connect")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.snapshot.connected and self.snapshot.state_ready:
                return self.snapshot
            await self.command("status")
            try:
                await self.wait_state(timeout=1.0)
            except Exception:
                pass
        raise TimeoutError("robot did not become connected/stateReady")
