"""Private loopback adapter. Reading context never issues a connect command."""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, *args, **kwargs):
        raise ValueError("Local Robot Service must not redirect")


class RobotClient:
    def __init__(self, *, base_url, token_file):
        url = urlsplit(base_url)
        if url.scheme != "http" or url.username or url.password or url.query or url.fragment or url.path not in ("", "/") or not ipaddress.ip_address(url.hostname).is_loopback:
            raise ValueError("Literal loopback Robot Service origin required")
        token_path = Path(token_file)
        if os.name == "posix" and token_path.stat().st_mode & 0o077:
            raise ValueError("Robot transport token requires owner-only permissions")
        token = token_path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("Invalid local Robot transport token")
        self._base, self._token = base_url.rstrip("/"), token

    async def _request(self, route, value=None, timeout=5):
        def run():
            data = None if value is None else json.dumps(value, allow_nan=False).encode("utf-8")
            request = urllib.request.Request(self._base + "/edge-control/v1/" + route, data=data,
                                             headers={"Content-Type": "application/json", "X-ThirdHand-Edge-Token": self._token})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise ValueError("Oversized local Robot response")
                return json.loads(raw)
        # A long ordinary command cannot block the priority stop request's coroutine.
        return await asyncio.to_thread(run)

    async def get_context(self):
        return await self._request("context")

    async def prepare_binding(self, boot_id):
        return await self._request("prepare-binding", {"bootId": boot_id})

    async def bind(self, context):
        return await self._request("bind", context)

    async def report_capture_health(self, *, boot_id, executor_epoch, writable, source_sequence):
        return await self._request("capture-health", {"bootId": boot_id, "executorEpoch": executor_epoch, "writable": writable, "sourceSequence": source_sequence})

    async def report_media_health(self, envelope):
        return await self._request("media-health", envelope, timeout=0.2)

    def iter_events(self):
        request = urllib.request.Request(self._base + "/edge-control/v1/events", headers={"Accept": "text/event-stream", "X-ThirdHand-Edge-Token": self._token})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=5) as response:
            if response.headers.get_content_type() != "text/event-stream":
                raise ValueError("Robot source stream unavailable")
            data = []
            while True:
                raw = response.readline(131073)
                if not raw:
                    raise ConnectionError("Robot source stream ended")
                if len(raw) > 131072:
                    raise ValueError("Oversized Robot source frame")
                line = raw.decode("utf-8").rstrip("\r\n")
                if not line:
                    if data:
                        yield json.loads("\n".join(data))
                        data = []
                elif line.startswith("data:"):
                    data.append(line[5:].lstrip(" "))
                    if sum(map(len, data)) > 131072:
                        raise ValueError("Oversized Robot source frame")

    async def submit_envelope(self, value):
        return await self._request("envelope", value["signedEnvelope"], timeout=5 if value["purpose"] == "stop" else 40)
