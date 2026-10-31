"""mTLS probe transport, deliberately independent of the Robot Service and SDK."""
import asyncio
import base64
import json
import os
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit
import uuid
from .probe_measurements import ProbeMeasurements

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect

from .protocol import ProtocolError, decode_b64, parse_json


@dataclass(frozen=True)
class DeviceConfig:
    url: str
    device_id: str
    boot_id: str
    certificate: Path
    private_key: Path
    ca_file: Path | None = None
    heartbeat_seconds: float = 2.0

    def __post_init__(self):
        url = urlsplit(self.url)
        if url.scheme != "wss" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != "/edge/v1/connect":
            raise ValueError("Exact credential-free WSS device endpoint required")
        uuid.UUID(self.device_id)
        uuid.UUID(self.boot_id)
        if not 0.1 <= self.heartbeat_seconds <= 5:
            raise ValueError("Invalid probe heartbeat interval")


def create_tls_context(config):
    key_path = Path(config.private_key)
    if os.name == "posix" and key_path.stat().st_mode & 0o077:
        raise ValueError("Device private key requires owner-only permissions")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(config.ca_file) if config.ca_file else None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(config.certificate), str(key_path))
    return context


@asynccontextmanager
async def authenticated_connection(config, *, executor_epoch=None):
    """Device authentication only; a bound executor still needs a separate ACK."""
    if executor_epoch is not None:
        uuid.UUID(executor_epoch)
    key = serialization.load_pem_private_key(Path(config.private_key).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Ed25519 device key required")
    cert = x509.load_pem_x509_certificate(Path(config.certificate).read_bytes())
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()
    clock = lambda: int(time.time() * 1000)
    async with connect(config.url, ssl=create_tls_context(config), proxy=None, compression=None,
                       open_timeout=10, close_timeout=2, ping_interval=10, ping_timeout=10,
                       max_size=16384, max_queue=8) as ws:
        async def receive():
            raw = await asyncio.wait_for(ws.recv(), timeout=7)
            if not isinstance(raw, str):
                raise ProtocolError("TEXT_MESSAGE_REQUIRED")
            return parse_json(raw.encode("utf-8"))
        await ws.send(json.dumps({"type": "hello", "protocol": 1, "deviceId": config.device_id,
                                               "bootId": config.boot_id, "executorEpoch": executor_epoch,
                                               "agentVersion": "0.1.0", "capabilities": ["control" if executor_epoch else "probe"]}))
        challenge = await receive()
        if not isinstance(challenge, dict) or set(challenge) != {"type", "payloadBase64url"} or challenge["type"] != "challenge":
            raise ProtocolError("EXPECTED_CHALLENGE")
        raw = decode_b64(challenge["payloadBase64url"], 4096)
        payload = parse_json(raw)
        expected = {"deviceId": config.device_id, "bootId": config.boot_id, "executorEpoch": executor_epoch, "certificateFingerprint": fingerprint}
        if not isinstance(payload, dict) or payload.get("schema") != 1 or payload.get("purpose") != "device_auth" or any(payload.get(k) != v for k, v in expected.items()):
            raise ProtocolError("INVALID_AUTH_CHALLENGE")
        for field in ("connectionId", "certificateId"):
            try:
                uuid.UUID(payload[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProtocolError("INVALID_AUTH_CHALLENGE") from exc
        if len(decode_b64(payload.get("nonce"), 43)) != 32:
            raise ProtocolError("INVALID_AUTH_CHALLENGE")
        issued, expires = payload.get("issuedAt"), payload.get("expiresAt")
        if type(issued) is not int or type(expires) is not int or issued > clock() + 500 or expires <= clock() or not 0 < expires - issued <= 5000:
            raise ProtocolError("EXPIRED_AUTH_CHALLENGE")
        signature = base64.urlsafe_b64encode(key.sign(raw)).decode().rstrip("=")
        await ws.send(json.dumps({"type": "proof", "signatureBase64url": signature}))
        welcome = await receive()
        context = {name: payload[name] for name in ("deviceId", "bootId", "executorEpoch", "certificateId", "connectionId")}
        if not isinstance(welcome, dict) or welcome.get("type") != "welcome" or welcome.get("controlAuthorized") is not False or welcome.get("context") != context:
            raise ProtocolError("INVALID_WELCOME")
        yield ws, context


async def connect_device(config, on_message=None, *, probe_count=None, probe_duration_seconds=None):
    """Bounded probe: no Robot Service, commands, SDK or automatic reconnect."""
    if probe_duration_seconds is not None and (probe_count is not None or
            not isinstance(probe_duration_seconds, (int, float)) or
            not 0 < probe_duration_seconds <= 3600):
        raise ValueError("Invalid bounded probe duration")
    async with authenticated_connection(config) as (ws, context):
        if on_message:
            await on_message({"type": "connected", "context": context, "controlAuthorized": False})
        count = 0
        measurements = ProbeMeasurements()
        deadline = time.monotonic() + probe_duration_seconds if probe_duration_seconds is not None else None
        while (probe_count is None or count < probe_count) and (count == 0 or deadline is None or time.monotonic() < deadline):
            nonce = uuid.uuid4().hex
            sent_ns = time.monotonic_ns()
            await ws.send(json.dumps({"type": "ping", "nonce": nonce}))
            raw = await asyncio.wait_for(ws.recv(), timeout=7)
            if not isinstance(raw, str):
                raise ProtocolError("TEXT_MESSAGE_REQUIRED")
            message = parse_json(raw.encode("utf-8"))
            if not isinstance(message, dict) or message.get("type") != "pong" or message.get("nonce") != nonce:
                raise ProtocolError("PROBE_ONLY")
            count += 1
            received_ns = time.monotonic_ns()
            rtt_ms = (received_ns - sent_ns) / 1_000_000
            measurements.add(rtt_ms, received_ns)
            if on_message:
                await on_message({"type": "heartbeat", "count": count, "rttMs": rtt_ms})
            if probe_count is None or count < probe_count:
                remaining = deadline - time.monotonic() if deadline is not None else config.heartbeat_seconds
                if remaining > 0:
                    await asyncio.sleep(min(config.heartbeat_seconds, remaining))
        return {"context": context, "heartbeats": count, "controlAuthorized": False,
                "measurements": measurements.report()}
