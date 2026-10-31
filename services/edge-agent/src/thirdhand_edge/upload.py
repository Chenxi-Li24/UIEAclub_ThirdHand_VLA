"""Independent telemetry HTTPS uploader; no control-channel queue or SDK import."""
import asyncio
import base64
import http.client
import json
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .outbox import Outbox
from .protocol import parse_json
from .transport import create_tls_context


class TelemetryUploadClient:
    """One upload worker owns one verified, reusable HTTPS connection.

    No connection, certificate, queue or lock is shared with motion control or
    media. Errors end the current drain; only a later explicit call can resend
    the same immutable outbox batch, never a Robot command.
    """
    def __init__(self, config):
        source = urlsplit(config.url)
        if source.scheme != 'wss' or not source.hostname or source.username or source.password or source.query or source.fragment or source.path != '/edge/v1/connect':
            raise ValueError('Exact credential-free device endpoint required')
        self._host, self._port = source.hostname, source.port or 443
        self._tls = create_tls_context(config)
        self._key = serialization.load_pem_private_key(Path(config.private_key).read_bytes(), password=None)
        if not isinstance(self._key, Ed25519PrivateKey):
            raise ValueError('Ed25519 upload key required')
        self._request_lock, self._state_lock = threading.Lock(), threading.Lock()
        self._drain_lock = asyncio.Lock()
        self._connection, self._closed = None, False

    @staticmethod
    def _close_connection(connection):
        if connection is not None:
            if connection.sock is not None:
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()

    def _discard(self, connection):
        with self._state_lock:
            if self._connection is connection:
                self._connection = None
        self._close_connection(connection)

    def close(self):
        with self._state_lock:
            self._closed = True
            connection, self._connection = self._connection, None
        self._close_connection(connection)

    def _post(self, value):
        data = json.dumps(value, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(data) > 360000:
            raise ValueError('Oversized telemetry upload')
        with self._request_lock:
            with self._state_lock:
                if self._closed:
                    raise ValueError('Upload client closed')
                connection = self._connection
                if connection is None:
                    connection = http.client.HTTPSConnection(self._host, self._port, context=self._tls, timeout=15)
                    connection.auto_open = 0  # Cancellation cannot implicitly reconnect this request.
                    self._connection = connection
            response = None
            try:
                if connection.sock is None:
                    connection.connect()
                with self._state_lock:
                    if self._closed:
                        raise ValueError('Upload client closed')
                connection.request('POST', '/edge/v1/telemetry-batches', body=data,
                                   headers={'Content-Type': 'application/json'})
                response = connection.getresponse()
                if response.status != 200:
                    raise ValueError('Telemetry upload rejected')
                raw = response.read(4097)
                if len(raw) > 4096:
                    raise ValueError('Oversized telemetry ACK')
                ack = parse_json(raw)
                if response.will_close:
                    self._discard(connection)
                return ack
            except Exception:
                self._discard(connection)
                raise
            finally:
                if response is not None:
                    response.close()

    async def upload_pending(self, outbox, *, limit=20):
        acknowledged = 0
        try:
            async with self._drain_lock:
                if self._closed:
                    return {'acknowledged': 0, 'error': 'UPLOAD_UNAVAILABLE'}
                for batch in outbox.pending_batches(limit=limit):
                    value = Outbox.wire_batch(batch)
                    value['signatureBase64url'] = base64.urlsafe_b64encode(self._key.sign(batch['payload'])).decode().rstrip('=')
                    try:
                        ack = await asyncio.to_thread(self._post, value)
                        if not isinstance(ack, dict) or set(ack) != {'batchId', 'digest', 'persisted'} or ack.get('batchId') != batch['batchId'] or ack.get('digest') != batch['digest'] or ack.get('persisted') is not True:
                            self._discard(self._connection)
                            return {'acknowledged': acknowledged, 'error': 'UPLOAD_ACK_MISMATCH'}
                        if outbox.ack_batch(batch['batchId'], batch['digest'], persisted=True):
                            acknowledged += 1
                    except Exception:
                        # Preserve the original batch and digest. Do not log
                        # arbitrary exception strings, headers or key material.
                        return {'acknowledged': acknowledged, 'error': 'UPLOAD_UNAVAILABLE'}
            return {'acknowledged': acknowledged}
        except asyncio.CancelledError:
            self.close()
            raise


async def upload_pending(config, outbox, *, limit=20):
    """Compatibility entry point; supervisors should retain a client per worker."""
    client = TelemetryUploadClient(config)
    try:
        return await client.upload_pending(outbox, limit=limit)
    finally:
        client.close()
