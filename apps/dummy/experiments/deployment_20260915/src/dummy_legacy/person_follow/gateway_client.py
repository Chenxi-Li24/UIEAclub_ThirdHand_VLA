from __future__ import annotations

import json
from urllib.parse import urlparse

import websockets


class GatewayClient:
    def __init__(self, url="ws://127.0.0.1:31023", timeout_s=1.0):
        parsed = urlparse(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 31023:
            raise ValueError("person-follow motion must use local gateway port 31023")
        self.url = url
        self.timeout_s = float(timeout_s)

    async def request(self, message):
        async with websockets.connect(self.url, open_timeout=self.timeout_s) as socket:
            await socket.send(json.dumps(message))
            return json.loads(await socket.recv())

    async def execute(self, message):
        return await self.request(message)
