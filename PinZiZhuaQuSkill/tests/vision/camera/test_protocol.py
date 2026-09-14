import io
import struct

import numpy as np
import pytest

from thirdhand_va.vision.camera.protocol import (
    CameraProtocolError,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    read_one_packet,
)

HEADER = struct.Struct("<8sIIIIQQIIII32s")


def make_packet(
    *,
    width: int = 2,
    height: int = 1,
    sequence: int = 7,
    stamp_ns: int = 99,
    serial: str = "250801DR48FP25002738",
    depth: np.ndarray | None = None,
    xyz: np.ndarray | None = None,
) -> bytes:
    pixels = width * height
    rgb = np.arange(pixels * 3, dtype=np.uint8)
    if depth is None:
        depth = np.array([0.4, np.nan], dtype="<f4")
    if xyz is None:
        xyz = np.array([[0.1, 0.2, 0.4], [np.nan, np.nan, np.nan]], dtype="<f4")
    depth_bytes = np.asarray(depth, dtype="<f4").reshape(pixels).tobytes()
    xyz_bytes = np.asarray(xyz, dtype="<f4").reshape(pixels, 3).tobytes()
    serial_bytes = serial.encode("ascii").ljust(32, b"\0")
    header = HEADER.pack(
        MAGIC,
        VERSION,
        HEADER_SIZE,
        width,
        height,
        sequence,
        stamp_ns,
        rgb.nbytes,
        len(depth_bytes),
        len(xyz_bytes),
        0,
        serial_bytes,
    )
    return header + rgb.tobytes() + depth_bytes + xyz_bytes


def test_protocol_v2_decodes_rgb_depth_and_xyz() -> None:
    frame = read_one_packet(
        io.BytesIO(make_packet()),
        expected_serial="250801DR48FP25002738",
    )

    assert frame.rgb.shape == (1, 2, 3)
    assert frame.depth_m.shape == (1, 2)
    assert frame.xyz_camera_m.shape == (1, 2, 3)
    assert frame.sequence == 7
    assert frame.monotonic_ns == 99
    assert np.isnan(frame.depth_m[0, 1])
    assert np.isnan(frame.xyz_camera_m[0, 1]).all()


def test_protocol_rejects_wrong_serial() -> None:
    with pytest.raises(CameraProtocolError, match="serial"):
        read_one_packet(
            io.BytesIO(make_packet(serial="old-camera")),
            expected_serial="250801DR48FP25002738",
        )


def test_protocol_rejects_depth_xyz_disagreement() -> None:
    depth = np.array([0.4, 0.5], dtype="<f4")
    xyz = np.array([[0.1, 0.2, 0.4], [0.0, 0.0, 0.7]], dtype="<f4")

    with pytest.raises(CameraProtocolError, match="depth/XYZ"):
        read_one_packet(
            io.BytesIO(make_packet(depth=depth, xyz=xyz)),
            expected_serial="250801DR48FP25002738",
        )
