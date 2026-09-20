"""Loopback-only HTTP boundary for the read-only Vision preview."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import ipaddress
import json
import logging
import threading
from typing import Any
from urllib.parse import parse_qs, urlsplit

from thirdhand_va.vision.adapters import FrameProvenance, build_mjpeg_part

from .service import PreviewService


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PreviewAccessPolicy:
    """Authorize either loopback-only use or an explicit tokenized LAN."""

    access_token: str | None = None
    allowed_networks: tuple[
        ipaddress.IPv4Network | ipaddress.IPv6Network,
        ...,
    ] = ()

    @classmethod
    def loopback_only(cls) -> "PreviewAccessPolicy":
        return cls()

    @classmethod
    def lan(
        cls,
        *,
        access_token: str,
        allowed_networks: Iterable[str],
    ) -> "PreviewAccessPolicy":
        if len(access_token.encode("utf-8")) < 22:
            raise ValueError("LAN preview token must contain at least 128 bits")
        try:
            networks = tuple(
                ipaddress.ip_network(value, strict=False)
                for value in allowed_networks
            )
        except ValueError as error:
            raise ValueError("LAN preview allowed network is invalid") from error
        if not networks:
            raise ValueError("LAN preview requires at least one allowed network")
        return cls(access_token=access_token, allowed_networks=networks)

    @property
    def requires_token(self) -> bool:
        return self.access_token is not None

    def validate_bind(self, host: str) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("preview host must be an IP address") from error
        if self.access_token is None:
            if not address.is_loopback:
                raise ValueError("preview host must be a loopback IP address")
            return
        if address.is_unspecified:
            raise ValueError("preview host must not be an unspecified address")

    def allows(self, client_host: str, supplied_token: str | None) -> bool:
        try:
            address = ipaddress.ip_address(client_host)
        except ValueError:
            return False
        if self.access_token is None:
            return address.is_loopback
        in_network = any(address in network for network in self.allowed_networks)
        return (
            in_network
            and supplied_token is not None
            and hmac.compare_digest(self.access_token, supplied_token)
        )


class _OwnedThreadingHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler, owner: "PreviewHttpServer"):
        self.preview_owner = owner
        super().__init__(server_address, handler)


class _PreviewRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _OwnedThreadingHttpServer

    def do_GET(self) -> None:
        path = self._authorized_path()
        if path is None:
            return
        if path == "/health":
            self._send_health()
            return
        if path == "/stream.mjpg":
            self._send_stream()
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"status": "not_found", "read_only": True},
        )

    def do_HEAD(self) -> None:
        if self._authorized_path() is not None:
            self._method_not_allowed()

    def do_POST(self) -> None:
        if self._authorized_path() is not None:
            self._method_not_allowed()

    def do_PUT(self) -> None:
        if self._authorized_path() is not None:
            self._method_not_allowed()

    def do_PATCH(self) -> None:
        if self._authorized_path() is not None:
            self._method_not_allowed()

    def do_DELETE(self) -> None:
        if self._authorized_path() is not None:
            self._method_not_allowed()

    def log_message(self, _format: str, *_args: Any) -> None:
        LOGGER.debug("preview_http client=%s", self.client_address[0])

    def _authorized_path(self) -> str | None:
        owner = self.server.preview_owner
        parsed = urlsplit(self.path)
        parameters = parse_qs(parsed.query, keep_blank_values=True)
        supplied_token: str | None = None
        if set(parameters) == {"token"} and len(parameters["token"]) == 1:
            supplied_token = parameters["token"][0]
        if owner.access_policy.requires_token and (
            set(parameters) != {"token"} or len(parameters["token"]) != 1
        ):
            self._send_forbidden()
            return None
        if not owner.access_policy.allows(
            str(self.client_address[0]),
            supplied_token,
        ):
            self._send_forbidden()
            return None
        return parsed.path

    def _send_forbidden(self) -> None:
        self._send_json(
            HTTPStatus.FORBIDDEN,
            {"status": "forbidden", "read_only": True},
        )

    def _method_not_allowed(self) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"status": "method_not_allowed", "read_only": True},
            extra_headers={"Allow": "GET"},
        )

    def _send_health(self) -> None:
        owner = self.server.preview_owner
        status = owner.service.status()
        self._send_json(
            HTTPStatus.OK,
            {
                "status": "ok",
                "mode": status.mode.value,
                "source": status.source_name,
                "last_sequence": status.last_sequence,
                "last_frame_at_ms": status.last_frame_at_ms,
                "relay_frame_age_ms": status.relay_frame_age_ms,
                "reconnect_count": status.reconnect_count,
                "clients": owner.client_count,
                "read_only": True,
            },
        )

    def _send_stream(self) -> None:
        owner = self.server.preview_owner
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            "multipart/x-mixed-replace; boundary=frame",
        )
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        owner._add_client()
        after_sequence = -1
        try:
            while not owner.stopping:
                frame = owner.service.wait_for_frame(
                    after_sequence,
                    timeout_s=0.5,
                )
                if frame is None:
                    continue
                part = build_mjpeg_part(
                    frame.jpeg,
                    FrameProvenance(
                        frame.sequence,
                        frame.published_monotonic_ns,
                        frame.observed_at_ms,
                    ),
                )
                self.wfile.write(part)
                self.wfile.flush()
                after_sequence = frame.sequence
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            owner._remove_client()
            self.close_connection = True

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)


class PreviewHttpServer:
    """Serve preview frames without exposing a business page or control API."""

    def __init__(
        self,
        service: PreviewService,
        *,
        host: str = "127.0.0.1",
        port: int = 8_765,
        access_policy: PreviewAccessPolicy | None = None,
    ) -> None:
        policy = access_policy or PreviewAccessPolicy.loopback_only()
        policy.validate_bind(host)
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65_535:
            raise ValueError("preview port must be within [0, 65535]")
        if not hasattr(service, "status") or not hasattr(service, "wait_for_frame"):
            raise TypeError("service must provide status() and wait_for_frame()")
        self.service = service
        self.host = host
        self.port = port
        self.access_policy = policy
        self._server: _OwnedThreadingHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._clients_lock = threading.Lock()
        self._clients = 0

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return self._clients

    def start(self) -> tuple[str, int]:
        if self._server is not None:
            address = self._server.server_address
            return str(address[0]), int(address[1])
        self._stopping.clear()
        server = _OwnedThreadingHttpServer(
            (self.host, self.port),
            _PreviewRequestHandler,
            self,
        )
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.1},
            name="vision-preview-http",
            daemon=True,
        )
        self._thread.start()
        address = server.server_address
        return str(address[0]), int(address[1])

    def stop(self) -> None:
        self._stopping.set()
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError("preview HTTP server did not stop")

    def _add_client(self) -> None:
        with self._clients_lock:
            self._clients += 1

    def _remove_client(self) -> None:
        with self._clients_lock:
            self._clients = max(0, self._clients - 1)


__all__ = ["PreviewAccessPolicy", "PreviewHttpServer"]
