"""Validated Python owner for the native XVisio RGB-D stream."""

from __future__ import annotations

from pathlib import Path
import socket
import struct
import subprocess
import threading
from typing import BinaryIO, NamedTuple

import numpy as np


MAGIC = b"XVRGBD2\0"
VERSION = 2
_HEADER = struct.Struct("<8sIIIIQQIIII32s")
HEADER_SIZE = _HEADER.size
MAX_PIXELS = 1920 * 1080
MAX_PAYLOAD_BYTES = MAX_PIXELS * (3 + 4 + 12)
SERIAL_BYTES = 32


class StreamProtocolError(RuntimeError):
    """The native driver emitted an invalid or incompatible packet."""


class PacketHeader(NamedTuple):
    width: int
    height: int
    sequence: int
    monotonic_ns: int
    rgb_bytes: int
    depth_bytes: int
    xyz_bytes: int
    serial: str


class XVisioFrame(NamedTuple):
    sequence: int
    monotonic_ns: int
    camera_serial: str
    rgb: np.ndarray
    depth_m: np.ndarray
    xyz_camera_m: np.ndarray


def default_executable(repo_root: str | Path) -> Path:
    """Return the ignored project-local native build output."""
    return Path(repo_root) / "runtime/build/xvisio/xvisio_rgbd_stream"


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    if size < 0 or size > MAX_PAYLOAD_BYTES:
        raise StreamProtocolError(f"refusing invalid read size: {size}")
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise EOFError("XVisio native stream closed")
        chunks.extend(chunk)
    return bytes(chunks)


def parse_header(data: bytes) -> PacketHeader:
    """Validate a protocol-v2 header before any payload allocation."""
    if len(data) != HEADER_SIZE:
        raise StreamProtocolError(
            f"header has {len(data)} bytes; expected {HEADER_SIZE}"
        )
    (
        magic,
        version,
        header_bytes,
        width,
        height,
        sequence,
        monotonic_ns,
        rgb_bytes,
        depth_bytes,
        xyz_bytes,
        flags,
        serial_raw,
    ) = _HEADER.unpack(data)
    if magic != MAGIC or version != VERSION or header_bytes != HEADER_SIZE:
        raise StreamProtocolError("unsupported XVisio stream protocol")
    pixels = width * height
    if width <= 0 or height <= 0 or pixels > MAX_PIXELS:
        raise StreamProtocolError("invalid camera frame dimensions")
    expected = (pixels * 3, pixels * 4, pixels * 3 * 4)
    if (rgb_bytes, depth_bytes, xyz_bytes) != expected:
        raise StreamProtocolError("payload byte counts do not match dimensions")
    if rgb_bytes + depth_bytes + xyz_bytes > MAX_PAYLOAD_BYTES:
        raise StreamProtocolError("camera payload exceeds configured limit")
    if sequence < 1 or monotonic_ns < 1:
        raise StreamProtocolError("sequence and timestamp must be positive")
    if flags != 0:
        raise StreamProtocolError("unsupported camera packet flags")
    try:
        serial = serial_raw.split(b"\0", 1)[0].decode("ascii")
    except UnicodeDecodeError as error:
        raise StreamProtocolError("camera serial is not ASCII") from error
    if not serial:
        raise StreamProtocolError("camera serial is empty")
    return PacketHeader(
        width,
        height,
        sequence,
        monotonic_ns,
        rgb_bytes,
        depth_bytes,
        xyz_bytes,
        serial,
    )


def read_one_packet(
    stream: BinaryIO,
    *,
    expected_serial: str,
) -> XVisioFrame:
    header = parse_header(_read_exact(stream, HEADER_SIZE))
    if header.serial != expected_serial:
        raise StreamProtocolError(
            f"camera serial {header.serial!r} does not match "
            f"expected serial {expected_serial!r}"
        )
    rgb = np.frombuffer(
        _read_exact(stream, header.rgb_bytes),
        dtype=np.uint8,
    ).reshape(header.height, header.width, 3).copy()
    depth = np.frombuffer(
        _read_exact(stream, header.depth_bytes),
        dtype="<f4",
    ).reshape(header.height, header.width).copy()
    xyz = np.frombuffer(
        _read_exact(stream, header.xyz_bytes),
        dtype="<f4",
    ).reshape(header.height, header.width, 3).copy()

    depth_valid = np.isfinite(depth) & (depth > 0.01) & (depth < 9.9)
    xyz_valid = (
        np.isfinite(xyz).all(axis=2)
        & (xyz[..., 2] > 0.01)
        & (xyz[..., 2] < 9.9)
    )
    if np.any(depth_valid != xyz_valid):
        raise StreamProtocolError("depth and XYZ validity masks disagree")
    if np.any(
        ~np.isclose(
            depth[depth_valid],
            xyz[..., 2][depth_valid],
            rtol=1e-3,
            atol=1e-4,
        )
    ):
        raise StreamProtocolError("depth and XYZ z values disagree")
    depth[~depth_valid] = np.nan
    xyz[~depth_valid] = np.nan
    return XVisioFrame(
        header.sequence,
        header.monotonic_ns,
        header.serial,
        rgb,
        depth,
        xyz,
    )


class XVisioStream:
    """Own one native camera process and retain only its newest frame."""

    def __init__(
        self,
        executable: str | Path,
        *,
        expected_serial: str,
        read_timeout_s: float = 3.0,
    ) -> None:
        if not expected_serial:
            raise ValueError("expected_serial is required")
        self.executable = Path(executable).resolve()
        self.expected_serial = expected_serial
        self.read_timeout_s = max(0.1, float(read_timeout_s))
        self._condition = threading.Condition()
        self._latest: XVisioFrame | None = None
        self._error: BaseException | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._socket: socket.socket | None = None
        self._reader: BinaryIO | None = None
        self._thread: threading.Thread | None = None
        self._stderr_tail = bytearray()
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._process is not None:
            raise RuntimeError("XVisio stream is already started")
        if not self.executable.is_file():
            raise RuntimeError(f"XVisio executable not found: {self.executable}")
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        # Keep packet reads blocking. A socket timeout can occur after only part
        # of an RGB-D packet has been consumed, which permanently destroys the
        # framing and used to stop the capture thread after a brief camera gap.
        # Callers still have a bounded wait through read_after(timeout_s).
        parent.settimeout(None)
        try:
            self._process = subprocess.Popen(
                [str(self.executable), str(child.fileno())],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                pass_fds=(child.fileno(),),
            )
        finally:
            child.close()
        self._socket = parent
        self._reader = parent.makefile("rb", buffering=0)
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="xvisio-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        self._thread = threading.Thread(
            target=self._read_loop,
            name="xvisio-reader",
            daemon=True,
        )
        self._thread.start()

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while chunk := process.stderr.read1(4096):
            self._stderr_tail.extend(chunk)
            if len(self._stderr_tail) > 65_536:
                del self._stderr_tail[:-65_536]

    def _read_loop(self) -> None:
        assert self._reader is not None
        sequence = 0
        timestamp = 0
        try:
            while True:
                frame = read_one_packet(
                    self._reader,
                    expected_serial=self.expected_serial,
                )
                if frame.sequence <= sequence or frame.monotonic_ns <= timestamp:
                    raise StreamProtocolError(
                        "sequence and timestamp must strictly increase"
                    )
                sequence = frame.sequence
                timestamp = frame.monotonic_ns
                with self._condition:
                    self._latest = frame
                    self._condition.notify_all()
        except BaseException as error:
            with self._condition:
                self._error = error
                self._condition.notify_all()

    def read_after(self, sequence: int, timeout_s: float) -> XVisioFrame | None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._error is not None
                or (
                    self._latest is not None
                    and self._latest.sequence > sequence
                ),
                timeout=max(0.0, float(timeout_s)),
            )
            if self._latest is not None and self._latest.sequence > sequence:
                return self._latest
            if self._error is not None:
                detail = self._stderr_tail.decode("utf-8", errors="replace").strip()
                failure = f"{type(self._error).__name__}: {self._error}"
                if detail:
                    failure += f"; SDK stderr: {detail}"
                raise RuntimeError(
                    f"XVisio native stream failed: {failure}"
                ) from self._error
            return None

    def diagnostics(self) -> dict[str, object]:
        process = self._process
        exit_code = None if process is None else process.poll()
        return {
            "executable": str(self.executable),
            "processRunning": process is not None and exit_code is None,
            "exitCode": exit_code,
            "stderr": self._stderr_tail.decode(
                "utf-8",
                errors="replace",
            ).strip() or None,
        }

    def close(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if self._reader is not None:
            self._reader.close()
        if self._socket is not None:
            self._socket.close()
        for thread in (self._thread, self._stderr_thread):
            if thread is not None:
                thread.join(timeout=1.0)
        if process is not None and process.stderr is not None:
            process.stderr.close()
        self._process = None
        self._socket = None
        self._reader = None
        self._thread = None
        self._stderr_thread = None

    def __enter__(self) -> "XVisioStream":
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
