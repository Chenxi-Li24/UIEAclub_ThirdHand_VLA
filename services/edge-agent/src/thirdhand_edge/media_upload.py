"""Separate mTLS device-signed publication lease request; never a robot command."""
import asyncio
import base64
from collections import deque
import http.client
import json
from pathlib import Path
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .protocol import ProtocolError, parse_json, decode_b64
from .transport import create_tls_context


class _CoalescedHTTPSConnection(http.client.HTTPSConnection):
    """Send one bounded report as one TLS write, including its HTTP headers.

    http.client normally sends the headers before the small JSON body. Losing
    that separate header segment made complete signed reports wait for TCP
    retransmission. Keep its HTTP framing, TLS verification and no-retry rules.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_parts = None
        self._report_size = 0

    def send(self, data):
        if self._report_parts is None:
            return super().send(data)
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('Bounded byte report required')
        self._report_size += len(data)
        if self._report_size > 32768:
            raise ValueError('Oversized media request')
        self._report_parts.append(bytes(data))

    def request(self, method, url, body=None, headers=None, *, encode_chunked=False):
        self._report_parts, self._report_size = [], 0
        try:
            super().request(method, url, body=body, headers=headers or {},
                            encode_chunked=encode_chunked)
            complete = b''.join(self._report_parts)
        finally:
            self._report_parts = None
            self._report_size = 0
        super().send(complete)


class MediaGrantClient:
    def __init__(self, config, *, on_timing=None, compact_renewals=False):
        source = urlsplit(config.url)
        self.url = urlunsplit(("https", source.netloc, "/edge/v1/media-grant", "", ""))
        self.host, self.port = source.hostname, source.port or 443
        self.tls = create_tls_context(config)
        self.key = serialization.load_pem_private_key(Path(config.private_key).read_bytes(), password=None)
        if not isinstance(self.key, Ed25519PrivateKey):
            raise ValueError("Ed25519 media device key required")
        self._request_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._connection = None
        self._closed = False
        self._recent_ms = deque(maxlen=8)
        self.on_timing = on_timing
        self.compact_renewals = compact_renewals is True
        self._credential_hint, self._cache_failed = None, False

    def remember_credentials(self, hint):
        # Called explicitly by the verified publication Gate, never by the raw
        # HTTP response parser. The hint has no JWT or signing key material.
        with self._state_lock:
            if hint is None:
                self._credential_hint = None
                return
            if self._closed or self._cache_failed:
                raise ProtocolError('MEDIA_CREDENTIAL_CACHE_TERMINATED')
            if not isinstance(hint, dict) or set(hint) != {'digest', 'publisherId', 'context'} or len(decode_b64(hint['digest'], 43)) != 32 or not isinstance(hint['context'], dict) or set(hint['context']) != {'deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId'}:
                raise ProtocolError('INVALID_MEDIA_CREDENTIAL_HINT')
            try:
                uuid.UUID(hint['publisherId'])
                for name, value in hint['context'].items():
                    if name != 'executorEpoch' or value is not None:
                        uuid.UUID(value)
            except (ValueError, TypeError, AttributeError) as error:
                raise ProtocolError('INVALID_MEDIA_CREDENTIAL_HINT') from error
            self._credential_hint = {'digest': hint['digest'], 'publisherId': hint['publisherId'], 'context': dict(hint['context'])}

    def _timing(self, value):
        try:
            if self.on_timing is not None:
                self.on_timing(dict(value))
        except Exception:
            pass  # Diagnostics cannot change publication authorization.

    @staticmethod
    def _close_connection(connection):
        if connection is not None:
            if connection.sock is not None:
                try:
                    connection.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            connection.close()

    def _discard(self, connection, *, failed=False):
        with self._state_lock:
            if self._connection is connection:
                self._connection = None
            if failed:
                self._credential_hint, self._cache_failed = None, True
        self._close_connection(connection)

    def close(self):
        with self._state_lock:
            self._closed = True
            self._credential_hint, self._cache_failed = None, True
            connection, self._connection = self._connection, None
        self._close_connection(connection)

    def _post(self, context, publisher_id, sequence, frame):
        queued_at = time.monotonic()
        with self._request_lock:
            with self._state_lock:
                if self._closed:
                    raise ProtocolError("MEDIA_GRANT_UNAVAILABLE")
                connection = self._connection
                if connection is None:
                    # Establish verified mTLS before dating the first report.
                    # Renewals reuse this connection; no redirects or proxies.
                    connection = _CoalescedHTTPSConnection(self.host, self.port, context=self.tls, timeout=5)
                    connection.auto_open = 0  # Cancellation must not implicitly reconnect after signing.
                    self._connection = connection
            response = None
            started, phase = time.monotonic(), 'connect'
            phase_started = started
            duration = lambda seconds: min(60000, max(0, round(seconds * 1000)))
            metrics = {'queueMs': duration(started - queued_at)}
            trace_id = uuid.uuid4().hex
            phase_fields = {'connect': 'connectMs', 'request_send': 'sendMs',
                            'response_headers': 'headersMs', 'response_body': 'bodyMs',
                            'response_parse': 'parseMs'}
            try:
                if connection.sock is None:
                    connection.connect()
                metrics['connectMs'] = duration(time.monotonic() - phase_started)
                with self._state_lock:
                    if self._closed:
                        raise ProtocolError("MEDIA_GRANT_UNAVAILABLE")
                connection.sock.settimeout(0.6)
                issued = time.time_ns() // 1000000
                payload = {"schema": 1, "purpose": "media_report", "context": context, "publisherId": publisher_id, "sequence": sequence, "frame": frame, "issuedAt": issued, "expiresAt": issued + 950}
                raw = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
                data = json.dumps({"payloadBase64url": base64.urlsafe_b64encode(raw).decode().rstrip("="), "signatureBase64url": base64.urlsafe_b64encode(self.key.sign(raw)).decode().rstrip("=")}).encode()
                phase = 'request_send'
                phase_started = time.monotonic()
                headers = {"Content-Type": "application/json"}
                if self.compact_renewals:
                    headers['X-ThirdHand-Media-Grant'] = 'compact-v1'
                    with self._state_lock:
                        hint = self._credential_hint
                        if not self._cache_failed and hint is not None and hint['publisherId'] == publisher_id and hint['context'] == context:
                            headers['X-ThirdHand-Media-Credentials'] = hint['digest']
                connection.request("POST", "/edge/v1/media-grant", body=data, headers=headers)
                metrics['sendMs'] = duration(time.monotonic() - phase_started)
                phase = 'response_headers'
                phase_started = time.monotonic()
                response = connection.getresponse()
                metrics['headersMs'] = duration(time.monotonic() - phase_started)
                if response.status != 200:
                    raise ProtocolError("MEDIA_GRANT_UNAVAILABLE")
                phase = 'response_body'
                phase_started = time.monotonic()
                value = response.read(24001)
                with self._state_lock:
                    if self._closed:
                        raise ProtocolError('MEDIA_GRANT_UNAVAILABLE')
                metrics['bodyMs'] = duration(time.monotonic() - phase_started)
                phase = 'response_parse'
                phase_started = time.monotonic()
                if len(value) > 24000:
                    raise ProtocolError("OVERSIZED_MEDIA_GRANT")
                message = parse_json(value)
                if not isinstance(message, dict) or set(message) != {"envelope"}:
                    raise ProtocolError("INVALID_MEDIA_GRANT")
                if response.will_close:
                    self._discard(connection)
                metrics['parseMs'] = duration(time.monotonic() - phase_started)
                elapsed = duration(time.monotonic() - started)
                self._recent_ms.append(elapsed)
                self._timing({'traceId': trace_id, 'stage': 'media_ack', 'outcome': 'accepted',
                              'phase': phase, 'elapsedMs': elapsed, **metrics})
                return message["envelope"]
            except Exception as exc:
                # Wrap in the worker: asyncio recreates bare TimeoutError and
                # would drop diagnostic attributes while crossing the thread.
                error = ProtocolError("MEDIA_GRANT_UNAVAILABLE")
                metrics[phase_fields[phase]] = duration(time.monotonic() - phase_started)
                elapsed = duration(time.monotonic() - started)
                error.media_metrics = {'phase': phase, 'elapsedMs': elapsed,
                                       'recentSuccessMs': list(self._recent_ms), **metrics}
                if response is not None:
                    error.media_metrics['httpStatus'] = response.status
                # Never retry a signed report or revive a failed lease.
                self._discard(connection, failed=True)
                self._timing({'traceId': trace_id, 'stage': 'media_ack', 'outcome': 'rejected',
                              'phase': phase, 'elapsedMs': elapsed, **metrics})
                raise error from exc
            finally:
                if response is not None:
                    response.close()

    async def request(self, context, publisher_id, sequence, frame):
        try:
            return await asyncio.to_thread(self._post, context, publisher_id, sequence, frame)
        except asyncio.CancelledError:
            self.close()
            raise
        except ProtocolError:
            raise
        except Exception as exc:
            raise ProtocolError("MEDIA_GRANT_UNAVAILABLE") from exc
