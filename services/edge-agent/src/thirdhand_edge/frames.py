"""One authenticated local camera stream, reused for all cloud viewers.

Missing capture metadata remains unavailable. Receipt time is never relabelled
as physical capture time or used to assert that remote motion is safe.
"""
from dataclasses import dataclass
import io
import ipaddress
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
import urllib.request


@dataclass(frozen=True)
class CameraFrame:
    width: int
    height: int
    rgb: bytes
    frame_id: str
    received_monotonic: float
    captured_at_us: str | None = None
    clock_quality: str = "unreliable"
    uncertainty_ms: float = 60000

    def health_report(self):
        if self.captured_at_us is None:
            return None
        return {"frameId": self.frame_id, "capturedAtUs": self.captured_at_us,
                "clockQuality": self.clock_quality, "uncertaintyMs": self.uncertainty_ms}


def decode_frame(jpeg, headers, *, received_monotonic):
    from PIL import Image
    sequence = headers.get("x-thirdhand-sequence", "")
    if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= 3 * 1024 * 1024 or not re.fullmatch(r"\d{1,19}", sequence):
        raise ValueError("Invalid bounded camera frame")
    try:
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.format != "JPEG" or not 1 <= image.width * image.height <= 2500000:
                raise ValueError("Unsupported camera dimensions")
            image.load()
            width, height, rgb = image.width, image.height, image.convert("RGB").tobytes()
    except Exception as exc:
        raise ValueError("Invalid camera JPEG") from exc
    captured, quality, uncertainty = None, "unreliable", 60000.0
    if "x-thirdhand-captured-at-us" in headers:
        value = headers["x-thirdhand-captured-at-us"]
        quality = headers.get("x-thirdhand-clock-quality", "unreliable")
        try:
            uncertainty = float(headers.get("x-thirdhand-clock-uncertainty-ms", "60000"))
        except ValueError as exc:
            raise ValueError("Invalid camera clock uncertainty") from exc
        if not re.fullmatch(r"\d{1,19}", value) or quality not in ("synchronized", "estimated", "unreliable") or not 0 <= uncertainty <= 60000:
            raise ValueError("Invalid camera capture metadata")
        captured = value
    return CameraFrame(width, height, rgb, sequence, received_monotonic, captured, quality, uncertainty)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, *args, **kwargs):
        raise ValueError("Camera source must not redirect")


class LocalCameraSource:
    def __init__(self, *, url, token_file):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/edge-media/v1/raw" or not ipaddress.ip_address(parsed.hostname).is_loopback:
            raise ValueError("Exact literal loopback private camera endpoint required")
        path = Path(token_file)
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError("Camera transport token requires owner-only permissions")
        token = path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[a-f0-9]{64}", token):
            raise ValueError("Invalid camera transport token")
        self.url, self.token = url, token

    def iter_frames(self):
        request = urllib.request.Request(self.url, headers={"X-ThirdHand-Media-Token": self.token})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=3) as response:
            if response.headers.get_content_type() != "multipart/x-mixed-replace":
                raise ValueError("Private camera stream unavailable")
            last = -1
            while True:
                line = response.readline(128)
                if line == b"\r\n":
                    continue
                if line != b"--frame\r\n":
                    raise ValueError("Invalid private camera boundary")
                headers, size = {}, 0
                while True:
                    line = response.readline(4097)
                    size += len(line)
                    if not line or len(line) > 4096 or size > 8192:
                        raise ValueError("Invalid camera headers")
                    if line == b"\r\n":
                        break
                    name, value = line.decode("ascii").split(":", 1)
                    name = name.lower().strip()
                    if name in headers:
                        raise ValueError("Duplicate camera header")
                    headers[name] = value.strip()
                if headers.get("content-type") != "image/jpeg" or not headers.get("content-length", "").isdigit():
                    raise ValueError("Invalid camera content type")
                length = int(headers["content-length"])
                if not 4 <= length <= 3 * 1024 * 1024:
                    raise ValueError("Invalid camera content length")
                jpeg = response.read(length)
                if len(jpeg) != length or response.read(2) != b"\r\n":
                    raise ValueError("Truncated camera frame")
                frame = decode_frame(jpeg, headers, received_monotonic=time.monotonic())
                if int(frame.frame_id) <= last:
                    raise ValueError("Camera source sequence restarted; fresh publication required")
                last = int(frame.frame_id)
                yield frame
