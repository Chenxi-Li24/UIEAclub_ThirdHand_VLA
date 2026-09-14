"""MJPEG serialization at the boundary between Vision and external consumers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class FrameProvenance:
    """Identity and timing metadata paired with one rendered Vision frame."""

    frame_id: int
    monotonic_ns: int
    observed_at_ms: int

    def __post_init__(self) -> None:
        if min(self.frame_id, self.monotonic_ns, self.observed_at_ms) < 0:
            raise ValueError("frame provenance values must be non-negative")


def build_mjpeg_part(jpeg: bytes, provenance: FrameProvenance) -> bytes:
    """Build one integrity-tagged multipart MJPEG frame."""

    if not jpeg:
        raise ValueError("JPEG payload must not be empty")
    sha = hashlib.sha256(jpeg).hexdigest()
    headers = (
        "--frame\r\n"
        "Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n"
        f"X-ThirdHand-Frame-Id: {provenance.frame_id}\r\n"
        f"X-ThirdHand-Monotonic-Ns: {provenance.monotonic_ns}\r\n"
        f"X-ThirdHand-Observed-At-Ms: {provenance.observed_at_ms}\r\n"
        f"X-ThirdHand-Image-Sha256: {sha}\r\n"
        "\r\n"
    ).encode("ascii")
    return headers + jpeg + b"\r\n"

