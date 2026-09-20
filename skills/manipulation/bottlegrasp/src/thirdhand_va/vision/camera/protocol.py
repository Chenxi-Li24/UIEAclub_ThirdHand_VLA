"""Versioned binary protocol for aligned XVisio RGB, depth, and XYZ frames."""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import BinaryIO

import numpy as np

from thirdhand_va.common.contracts import RgbdFrame

MAGIC = b"XVRGBD2\0"
VERSION = 2
_HEADER = struct.Struct("<8sIIIIQQIIII32s")
HEADER_SIZE = _HEADER.size
MAX_PIXELS = 1920 * 1080
SERIAL_BYTES = 32


class CameraProtocolError(RuntimeError):
    """The native camera process emitted an invalid or incompatible packet."""


@dataclass(frozen=True, slots=True)
class PacketHeader:
    width: int
    height: int
    sequence: int
    monotonic_ns: int
    rgb_bytes: int
    depth_bytes: int
    xyz_bytes: int
    serial: str


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise EOFError("XVisio native stream closed")
        chunks.extend(chunk)
    return bytes(chunks)


def decode_packet_header(data: bytes) -> PacketHeader:
    if len(data) != HEADER_SIZE:
        raise CameraProtocolError(
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
        raise CameraProtocolError("unsupported XVisio camera protocol")
    pixels = width * height
    if width <= 0 or height <= 0 or pixels > MAX_PIXELS:
        raise CameraProtocolError("invalid camera frame dimensions")
    if (
        rgb_bytes != pixels * 3
        or depth_bytes != pixels * 4
        or xyz_bytes != pixels * 3 * 4
    ):
        raise CameraProtocolError("payload byte counts do not match dimensions")
    if sequence < 1 or monotonic_ns < 1:
        raise CameraProtocolError("sequence and timestamp must be positive")
    if flags != 0:
        raise CameraProtocolError("unsupported camera packet flags")
    try:
        serial = serial_raw.split(b"\0", 1)[0].decode("ascii")
    except UnicodeDecodeError as error:
        raise CameraProtocolError("camera serial is not ASCII") from error
    if not serial:
        raise CameraProtocolError("camera serial is empty")
    return PacketHeader(
        width=width,
        height=height,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        rgb_bytes=rgb_bytes,
        depth_bytes=depth_bytes,
        xyz_bytes=xyz_bytes,
        serial=serial,
    )


def read_one_packet(
    stream: BinaryIO,
    *,
    expected_serial: str,
) -> RgbdFrame:
    header = decode_packet_header(_read_exact(stream, HEADER_SIZE))
    if header.serial != expected_serial:
        raise CameraProtocolError(
            f"camera serial {header.serial!r} does not match "
            f"expected serial {expected_serial!r}"
        )
    rgb = np.frombuffer(
        _read_exact(stream, header.rgb_bytes), dtype=np.uint8
    ).reshape(header.height, header.width, 3)
    depth = np.frombuffer(
        _read_exact(stream, header.depth_bytes), dtype="<f4"
    ).reshape(header.height, header.width).copy()
    xyz = np.frombuffer(
        _read_exact(stream, header.xyz_bytes), dtype="<f4"
    ).reshape(header.height, header.width, 3).copy()

    depth_valid = np.isfinite(depth) & (depth > 0.01) & (depth < 9.9)
    xyz_valid = (
        np.isfinite(xyz).all(axis=2)
        & (xyz[..., 2] > 0.01)
        & (xyz[..., 2] < 9.9)
    )
    if np.any(depth_valid != xyz_valid):
        raise CameraProtocolError("depth/XYZ validity masks disagree")
    if np.any(
        ~np.isclose(
            depth[depth_valid],
            xyz[..., 2][depth_valid],
            rtol=1e-3,
            atol=1e-4,
        )
    ):
        raise CameraProtocolError("depth/XYZ z values disagree")
    invalid = ~depth_valid
    depth[invalid] = np.nan
    xyz[invalid] = np.nan
    return RgbdFrame(
        sequence=header.sequence,
        monotonic_ns=header.monotonic_ns,
        camera_serial=header.serial,
        rgb=rgb,
        depth_m=depth,
        xyz_camera_m=xyz,
    )


def encode_packet(frame: RgbdFrame) -> bytes:
    """Encode a validated frame; used by deterministic tests and replay tools."""
    serial = frame.camera_serial.encode("ascii")
    if len(serial) >= SERIAL_BYTES:
        raise CameraProtocolError("camera serial is too long for protocol v2")
    height, width = frame.depth_m.shape
    rgb = np.ascontiguousarray(frame.rgb, dtype=np.uint8)
    depth = np.ascontiguousarray(frame.depth_m, dtype="<f4")
    xyz = np.ascontiguousarray(frame.xyz_camera_m, dtype="<f4")
    serial_field = serial.ljust(SERIAL_BYTES, b"\0")
    header = _HEADER.pack(
        MAGIC,
        VERSION,
        HEADER_SIZE,
        width,
        height,
        frame.sequence,
        frame.monotonic_ns,
        rgb.nbytes,
        depth.nbytes,
        xyz.nbytes,
        0,
        serial_field,
    )
    return header + rgb.tobytes() + depth.tobytes() + xyz.tobytes()
