"""Read-only client for timestamped Lumos JPEG snapshots."""

from __future__ import annotations

import urllib.error
import urllib.request
from http.client import HTTPResponse
from urllib.parse import urlsplit

import cv2
import numpy as np
from vision.online_frames import RgbFrame
from vision.types import FrameStamp

from .contracts import ModelContractError


class LumosSnapshotClient:
    def __init__(
        self,
        url: str,
        timeout_s: float,
        *,
        allow_remote: bool = False,
        max_payload_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        parsed = urlsplit(str(url))
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.path not in {"/frame.jpg", "/frame_raw.jpg"}
        ):
            raise ModelContractError(
                "Lumos snapshot URL must be an HTTP /frame.jpg or /frame_raw.jpg endpoint"
            )
        if not allow_remote and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ModelContractError("Lumos snapshot URL must use a loopback host")
        timeout = float(timeout_s)
        if not np.isfinite(timeout) or timeout <= 0.0:
            raise ModelContractError("Lumos snapshot timeout must be finite and positive")
        if not isinstance(max_payload_bytes, int) or max_payload_bytes < 1:
            raise ModelContractError("Lumos snapshot payload limit must be positive")
        self.url = url
        self.timeout_s = timeout
        self.max_payload_bytes = max_payload_bytes
        self._last_server_sequence = -1
        self._last_server_monotonic_ns = 0

    @staticmethod
    def _provenance(response: HTTPResponse) -> tuple[int, int]:
        raw_sequence = response.headers.get("X-Lumos-Sequence")
        raw_monotonic_ns = response.headers.get("X-Lumos-Monotonic-Ns")
        try:
            sequence = int(raw_sequence) if raw_sequence is not None else -1
            monotonic_ns = int(raw_monotonic_ns) if raw_monotonic_ns is not None else -1
        except ValueError as error:
            raise ModelContractError("Lumos snapshot provenance headers are invalid") from error
        if sequence < 0 or monotonic_ns <= 0:
            raise ModelContractError("Lumos snapshot provenance headers are missing or invalid")
        return sequence, monotonic_ns

    def read(self, after_sequence: int) -> RgbFrame | None:
        if not isinstance(after_sequence, int) or after_sequence < -1:
            raise ModelContractError("after_sequence must be an integer no smaller than -1")
        try:
            separator = "&" if "?" in self.url else "?"
            request_url = f"{self.url}{separator}after={after_sequence}"
            response = urllib.request.urlopen(request_url, timeout=self.timeout_s)
        except urllib.error.HTTPError as error:
            raise ModelContractError(
                f"Lumos snapshot endpoint returned HTTP {error.code}"
            ) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ModelContractError(f"Lumos snapshot request failed: {error}") from error

        with response:
            if getattr(response, "status", 200) != 200:
                raise ModelContractError(
                    f"Lumos snapshot endpoint returned HTTP {response.status}"
                )
            if response.headers.get_content_type() != "image/jpeg":
                raise ModelContractError("Lumos snapshot response must be image/jpeg")
            sequence, monotonic_ns = self._provenance(response)
            new_epoch = (
                self._last_server_sequence >= 0
                and sequence < self._last_server_sequence
                and monotonic_ns > self._last_server_monotonic_ns
            )
            self._last_server_sequence = sequence
            self._last_server_monotonic_ns = monotonic_ns
            if sequence <= after_sequence and not new_epoch:
                return None
            raw_length = response.headers.get("Content-Length")
            if raw_length is not None:
                try:
                    declared_length = int(raw_length)
                except ValueError as error:
                    raise ModelContractError("Lumos snapshot payload length is invalid") from error
                if declared_length < 1 or declared_length > self.max_payload_bytes:
                    raise ModelContractError("Lumos snapshot payload exceeds byte limit")
            payload = response.read(self.max_payload_bytes + 1)
        if not payload or len(payload) > self.max_payload_bytes:
            raise ModelContractError("Lumos snapshot payload exceeds byte limit")
        encoded = np.frombuffer(payload, dtype=np.uint8)
        image_bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image_bgr is None:
            raise ModelContractError("Lumos snapshot payload is not a valid JPEG")
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        return RgbFrame(
            stamp=FrameStamp("lumos_rgb", sequence, monotonic_ns),
            image_rgb=image_rgb,
        )
