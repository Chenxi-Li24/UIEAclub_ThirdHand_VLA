"""Disabled-by-default structured model transports for shadow verification."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ..runtime.trace import TraceError, canonical_json

MAX_HTTP_RESPONSE_BYTES = 1024 * 1024
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class ModelTransportError(RuntimeError):
    """Raised when a structured model request or response is unsafe."""


class ModelTransportDisabled(ModelTransportError):
    """Raised when an outbound transport was not explicitly enabled."""


def _safe_endpoint(value: str) -> bool:
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname.lower() in LOOPBACK_HOSTS


class HttpTransportConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    enabled: bool = False
    endpoint: str = Field(min_length=1)
    allowed_endpoints: tuple[str, ...] = Field(min_length=1)
    timeout_s: float = Field(default=10.0, gt=0.0, le=60.0)
    max_response_bytes: int = Field(
        default=MAX_HTTP_RESPONSE_BYTES,
        ge=1,
        le=MAX_HTTP_RESPONSE_BYTES,
    )
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def checked_endpoint(self) -> HttpTransportConfig:
        if len(self.allowed_endpoints) != len(set(self.allowed_endpoints)):
            raise ValueError("allowed_endpoints must be unique")
        if self.endpoint not in self.allowed_endpoints:
            raise ValueError("endpoint must exactly match the allow-list")
        if any(not _safe_endpoint(value) for value in self.allowed_endpoints):
            raise ValueError("endpoints require HTTPS or loopback HTTP without query credentials")
        return self


class ByteSender(Protocol):
    def send(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: float,
        max_response_bytes: int,
    ) -> bytes:
        """Send one bounded request and return response bytes."""


class HttpxByteSender:
    """Lazy HTTP implementation; importing this module does not require httpx."""

    def send(
        self,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_s: float,
        max_response_bytes: int,
    ) -> bytes:
        try:
            import httpx
        except ImportError as exc:
            raise ModelTransportError("httpx is unavailable") from exc
        data = bytearray()
        try:
            with httpx.Client(timeout=timeout_s, follow_redirects=False) as client:
                with client.stream(
                    "POST",
                    endpoint,
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > max_response_bytes:
                            raise ModelTransportError("model response exceeds byte limit")
        except ModelTransportError:
            raise
        except Exception as exc:
            if type(exc).__name__.lower().endswith("timeout"):
                raise TimeoutError("model request timed out") from exc
            raise ModelTransportError(f"model HTTP request failed: {type(exc).__name__}") from exc
        return bytes(data)


def _checked_payload(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ModelTransportError("model payload must be a JSON object")
    try:
        canonical_json(payload)
    except TraceError as exc:
        raise ModelTransportError(f"model payload must be finite JSON: {exc}") from exc
    return payload


def _checked_response(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ModelTransportError("model response must be a JSON object")
    try:
        canonical_json(value)
    except TraceError as exc:
        raise ModelTransportError(f"model response must be finite JSON: {exc}") from exc
    return value


class DisabledTransport:
    def request(self, payload: dict[str, object]) -> dict[str, object]:
        del payload
        raise ModelTransportDisabled("model transport is disabled")


class InjectedTransport:
    """Call an injected in-process handler while enforcing the JSON boundary."""

    def __init__(self, handler: Callable[[dict[str, object]], object]) -> None:
        self._handler = handler

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        return _checked_response(self._handler(_checked_payload(payload)))


class AllowListedHttpTransport:
    def __init__(
        self,
        config: HttpTransportConfig,
        *,
        sender: ByteSender | None = None,
    ) -> None:
        self.config = config
        self._sender = sender or HttpxByteSender()

    def request(self, payload: dict[str, object]) -> dict[str, object]:
        if not self.config.enabled:
            raise ModelTransportDisabled("model HTTP transport is disabled")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key is not None:
            headers["Authorization"] = (
                f"Bearer {self.config.api_key.get_secret_value()}"
            )
        response = self._sender.send(
            self.config.endpoint,
            headers,
            _checked_payload(payload),
            self.config.timeout_s,
            self.config.max_response_bytes,
        )
        if len(response) > self.config.max_response_bytes:
            raise ModelTransportError("model response exceeds byte limit")
        try:
            decoded = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelTransportError("model response must be UTF-8 JSON") from exc
        return _checked_response(decoded)

    def audit_metadata(self) -> dict[str, object]:
        return {
            "enabled": self.config.enabled,
            "endpoint": self.config.endpoint,
            "has_api_key": self.config.api_key is not None,
            "max_response_bytes": self.config.max_response_bytes,
            "timeout_s": self.config.timeout_s,
        }


__all__ = [
    "AllowListedHttpTransport",
    "DisabledTransport",
    "HttpTransportConfig",
    "InjectedTransport",
    "ModelTransportDisabled",
    "ModelTransportError",
]
