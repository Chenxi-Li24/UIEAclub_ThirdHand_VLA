from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

import websockets


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
