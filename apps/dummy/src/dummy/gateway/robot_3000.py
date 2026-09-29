from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

import websockets


def extract_joints(message):
    if not isinstance(message, dict) or message.get("type") != "robot_state":
        return None
    values = message.get("joints_deg", message.get("joints"))
    if not isinstance(values, list) or len(values) != 6:
        return None
    try:
        joints = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    return joints if all(__import__("math").isfinite(value) for value in joints) else None


class Robot3000Adapter:
    def __init__(self, url="ws://127.0.0.1:3000/ws", timeout_s=1.0):
        parsed = urlparse(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 3000:
            raise ValueError("gateway upstream must be local robot service port 3000")
        self.url = url
        self.timeout_s = float(timeout_s)

    async def send(self, message):
        async with websockets.connect(self.url, open_timeout=self.timeout_s) as socket:
            await socket.send(json.dumps(message))
            return json.loads(await asyncio.wait_for(socket.recv(), self.timeout_s))

    async def get_joints(self):
        async with websockets.connect(self.url, open_timeout=self.timeout_s) as socket:
            await socket.send(json.dumps({"cmd": "get_state"}))
            deadline = asyncio.get_running_loop().time() + self.timeout_s
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("fresh robot_state unavailable from 3000")
                message = json.loads(await asyncio.wait_for(socket.recv(), remaining))
                joints = extract_joints(message)
                if joints is not None:
                    return joints
