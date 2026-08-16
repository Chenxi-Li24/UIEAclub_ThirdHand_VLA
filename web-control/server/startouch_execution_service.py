#!/usr/bin/env python3
"""Loopback-only HTTP service for the PART D execution contract.

The service exposes the fixed-waypoint adapter on ``127.0.0.1:7788`` by
default.  It supports software simulation and a local, no-motion dry-run.
Real mode is always refused.  This process never starts the Startouch bridge,
imports the vendor SDK, opens CAN, or sends a motion/gripper command.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import threading
import time
import uuid
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7788
DEFAULT_REQUEST_TIMEOUT_S = 5.0
DEFAULT_MAX_BODY_BYTES = 1_048_576

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "web-control" / "scripts" / "startouch_fixed_waypoint_adapter.py"


def _load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("part_d_fixed_waypoint_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load execution adapter: {ADAPTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = _load_adapter()


def _env_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _env_float(name: str, default: float) -> float:
    value = float(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _safe_identifier(value: Any, fallback: str) -> str:
    if isinstance(value, str) and adapter.IDENTIFIER_RE.fullmatch(value):
        return value
    return fallback


def build_service_error(
    request: Mapping[str, Any] | None,
    *,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    """Build a schema-valid ``service.error`` for HTTP/protocol failures."""

    request = request or {}
    request_message_id = request.get("messageId")
    result: dict[str, Any] = {
        "schemaVersion": "1.0",
        "type": "service.error",
        "messageId": f"msg-{uuid.uuid4().hex}",
        "replyTo": (
            request_message_id
            if isinstance(request_message_id, str)
            and adapter.IDENTIFIER_RE.fullmatch(request_message_id)
            else None
        ),
        "sessionId": _safe_identifier(request.get("sessionId"), "session-execution-error"),
        "traceId": _safe_identifier(request.get("traceId"), "trace-execution-error"),
        "ts": int(time.time() * 1000),
        "source": "robot",
        "target": "orchestrator",
        "mode": adapter._safe_mode(request.get("mode")),
        "status": "failure",
        "payload": {"stage": "execution"},
        "error": {
            "code": _safe_identifier(code, "execution_service_error"),
            "message": str(message)[:1000] or "execution service error",
            "retryable": retryable,
        },
    }
    validator = adapter._contract_validator(ROOT)
    adapter._validate_contract_message(validator, result, "service.error")
    return result


class IdentityBindingStore:
    """Optional read-only binding supplied by the Orchestrator.

    The JSON file is a mapping from ``sessionId`` to an object containing
    ``traceId``, ``candidateId``, ``decisionId`` and ``targetId``.  It is read
    for every request so the Orchestrator can atomically replace it between
    sessions.  No file means that only the identifiers and safety booleans in
    the contract message itself can be checked.
    """

    def __init__(self, path: Path | None):
        self.path = path

    def resolve(self, request: Mapping[str, Any]) -> Mapping[str, str] | None:
        if self.path is None:
            return None
        try:
            text = self.path.read_text(encoding="utf-8")
            document = adapter.loads_json_strict(text)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise IdentityBindingError(f"cannot read trusted identity bindings: {exc}") from exc
        if not isinstance(document, Mapping):
            raise IdentityBindingError("identity binding file must contain a JSON object")
        session_id = request.get("sessionId")
        binding = document.get(session_id)
        if not isinstance(binding, Mapping):
            return {}
        return binding


class IdentityBindingError(RuntimeError):
    """The optional trusted Orchestrator binding could not be used safely."""


class ExecutionProcessor:
    """Single-admission processor for mutually exclusive execution requests."""

    def __init__(self, binding_store: IdentityBindingStore | None = None):
        self.binding_store = binding_store or IdentityBindingStore(None)
        self._execution_lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self._execution_lock.locked()

    def _busy_result(self, request: Mapping[str, Any]) -> dict[str, Any]:
        validator = adapter._contract_validator(ROOT)
        try:
            adapter._validate_contract_message(validator, request, "execution.request")
        except adapter.AdapterBlocked:
            return adapter.process_execution_request(request, root=ROOT)
        error = adapter.AdapterBlocked(
            "concurrent_execution_blocked",
            "another execution request is active; no hardware command was sent",
        )
        result = adapter._build_result(
            request,
            status="blocked",
            executed_steps=0,
            now_ms=int(time.time() * 1000),
            error=error,
        )
        adapter._validate_contract_message(validator, result, "blocked execution.result")
        return result

    def process(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not self._execution_lock.acquire(blocking=False):
            return self._busy_result(request)
        try:
            expected_identity = self.binding_store.resolve(request)
            return adapter.process_execution_request(
                request,
                root=ROOT,
                expected_identity=expected_identity,
            )
        finally:
            self._execution_lock.release()


class ExecutionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        processor: ExecutionProcessor,
        *,
        request_timeout_s: float,
        max_body_bytes: int,
    ):
        super().__init__(address, ExecutionRequestHandler)
        self.processor = processor
        self.request_timeout_s = request_timeout_s
        self.max_body_bytes = max_body_bytes


class ExecutionRequestHandler(BaseHTTPRequestHandler):
    server: ExecutionHTTPServer
    server_version = "ThirdHandExecution/1.0"
    sys_version = ""

    def _send_json(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        """Keep unsupported HTTP methods and protocol errors in JSON."""

        detail = message or explain or HTTPStatus(code).phrase
        self._send_json(
            code,
            build_service_error(
                None,
                code="http_protocol_error",
                message=detail,
            ),
        )

    def _health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "part_d_execution",
            "adapterId": adapter.ADAPTER_ID,
            "supportedExecutionPlanKinds": ["fixed_waypoint_a_to_b"],
            "validatedModes": ["simulate", "dry-run"],
            "realModeEnabled": False,
            "busy": self.server.processor.busy,
            "hardwareAccess": False,
            "bridgeStarted": False,
            "sdkInitialized": False,
            "canOpened": False,
            "motionCommandsEnabled": False,
        }

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, self._health())
            return
        if self.path == "/v1/capabilities":
            payload = self._health()
            payload.update(
                {
                    "executionEndpoint": "/v1/execution",
                    "transport": "http_json",
                    "authentication": "none_loopback_only",
                    "maxBodyBytes": self.server.max_body_bytes,
                    "requestReadTimeoutSeconds": self.server.request_timeout_s,
                }
            )
            self._send_json(HTTPStatus.OK, payload)
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            build_service_error(None, code="not_found", message="endpoint not found"),
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/execution":
            self._send_json(
                HTTPStatus.NOT_FOUND,
                build_service_error(None, code="not_found", message="endpoint not found"),
            )
            return
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                build_service_error(
                    None,
                    code="unsupported_media_type",
                    message="Content-Type must be application/json",
                ),
            )
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0:
            self._send_json(
                HTTPStatus.LENGTH_REQUIRED,
                build_service_error(
                    None,
                    code="content_length_required",
                    message="a valid Content-Length header is required",
                ),
            )
            return
        if length > self.server.max_body_bytes:
            self._send_json(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                build_service_error(
                    None,
                    code="request_too_large",
                    message="request body exceeds the configured limit",
                ),
            )
            return
        self.connection.settimeout(self.server.request_timeout_s)
        request: Mapping[str, Any] | None = None
        try:
            document = adapter.loads_json_strict(self.rfile.read(length).decode("utf-8"))
            if not isinstance(document, Mapping):
                raise ValueError("request JSON must be an object")
            request = document
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                build_service_error(
                    request,
                    code="invalid_json",
                    message=f"invalid request body: {exc}",
                ),
            )
            return
        try:
            result = self.server.processor.process(request)
        except IdentityBindingError as exc:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                build_service_error(
                    request,
                    code="identity_binding_unavailable",
                    message=str(exc),
                    retryable=True,
                ),
            )
            return
        except OSError as exc:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                build_service_error(
                    request,
                    code="execution_preflight_unavailable",
                    message=str(exc),
                    retryable=True,
                ),
            )
            return
        except Exception as exc:  # fail closed at the HTTP boundary
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                build_service_error(
                    request,
                    code="execution_service_error",
                    message=str(exc),
                ),
            )
            return
        status = (
            HTTPStatus.CONFLICT
            if result.get("error", {}).get("code") == "concurrent_execution_blocked"
            else HTTPStatus.OK
        )
        self._send_json(status, result)

    def log_message(self, format: str, *args: Any) -> None:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        print(f"{timestamp} execution-http {self.client_address[0]} {format % args}")


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    binding_file: Path | None = None,
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
) -> ExecutionHTTPServer:
    if host != DEFAULT_HOST:
        raise ValueError("PART D delivery is loopback-only; host must be 127.0.0.1")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    adapter._contract_validator(ROOT)
    adapter._route_from_existing_runner(ROOT)
    if binding_file is not None and not binding_file.is_file():
        raise ValueError(f"identity binding file does not exist: {binding_file}")
    processor = ExecutionProcessor(IdentityBindingStore(binding_file))
    return ExecutionHTTPServer(
        (host, port),
        processor,
        request_timeout_s=request_timeout_s,
        max_body_bytes=max_body_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("THIRDHAND_ROBOT_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port",
        type=int,
        default=_env_int("THIRDHAND_ROBOT_PORT", DEFAULT_PORT),
    )
    parser.add_argument(
        "--binding-file",
        type=Path,
        default=(
            Path(os.environ["THIRDHAND_EXECUTION_BINDINGS_FILE"])
            if os.environ.get("THIRDHAND_EXECUTION_BINDINGS_FILE")
            else None
        ),
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=_env_float("THIRDHAND_ROBOT_REQUEST_TIMEOUT_S", DEFAULT_REQUEST_TIMEOUT_S),
    )
    parser.add_argument(
        "--max-body-bytes",
        type=int,
        default=_env_int("THIRDHAND_ROBOT_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES),
    )
    args = parser.parse_args()

    server = create_server(
        host=args.host,
        port=args.port,
        binding_file=args.binding_file,
        request_timeout_s=args.request_timeout,
        max_body_bytes=args.max_body_bytes,
    )
    address, port = server.server_address[:2]
    print(
        json.dumps(
            {
                "event": "execution_service_ready",
                "endpoint": f"http://{address}:{port}/v1/execution",
                "health": f"http://{address}:{port}/health",
                "realModeEnabled": False,
                "hardwareAccess": False,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print('{"event":"execution_service_stopped"}', flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
