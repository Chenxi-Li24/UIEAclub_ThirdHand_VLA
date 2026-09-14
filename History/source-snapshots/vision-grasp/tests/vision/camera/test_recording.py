import json
from pathlib import Path

import numpy as np
import pytest

from thirdhand_va.vision.camera.recording import (
    RecordingError,
    read_frame_bundle,
    write_frame_bundle,
)
from thirdhand_va.common.contracts import RgbdFrame


@pytest.fixture
def rgbd_frame() -> RgbdFrame:
    depth = np.array([[0.4, np.nan], [0.5, 0.6]], dtype=np.float32)
    xyz = np.zeros((2, 2, 3), dtype=np.float32)
    xyz[..., 0] = 0.1
    xyz[..., 1] = -0.05
    xyz[..., 2] = depth
    xyz[~np.isfinite(depth)] = np.nan
    return RgbdFrame(
        sequence=17,
        monotonic_ns=123456,
        camera_serial="250801DR48FP25002738",
        rgb=np.arange(12, dtype=np.uint8).reshape(2, 2, 3),
        depth_m=depth,
        xyz_camera_m=xyz,
    )


def test_recording_round_trip_preserves_arrays(
    tmp_path: Path,
    rgbd_frame: RgbdFrame,
) -> None:
    content_id = write_frame_bundle(tmp_path, rgbd_frame)
    loaded = read_frame_bundle(tmp_path)

    assert content_id.startswith("sha256:")
    assert loaded.sequence == rgbd_frame.sequence
    assert loaded.monotonic_ns == rgbd_frame.monotonic_ns
    assert loaded.camera_serial == rgbd_frame.camera_serial
    np.testing.assert_array_equal(loaded.rgb, rgbd_frame.rgb)
    np.testing.assert_array_equal(loaded.depth_m, rgbd_frame.depth_m)
    np.testing.assert_array_equal(loaded.xyz_camera_m, rgbd_frame.xyz_camera_m)


def test_recording_rejects_tampered_metadata(
    tmp_path: Path,
    rgbd_frame: RgbdFrame,
) -> None:
    write_frame_bundle(tmp_path, rgbd_frame)
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RecordingError, match="content"):
        read_frame_bundle(tmp_path)


def test_recording_rejects_tampered_arrays(
    tmp_path: Path,
    rgbd_frame: RgbdFrame,
) -> None:
    write_frame_bundle(tmp_path, rgbd_frame)
    with np.load(tmp_path / "arrays.npz", allow_pickle=False) as stored:
        rgb = stored["rgb"].copy()
        depth = stored["depth_m"].copy()
        xyz = stored["xyz_camera_m"].copy()
    rgb[0, 0, 0] ^= 1
    np.savez_compressed(
        tmp_path / "arrays.npz",
        rgb=rgb,
        depth_m=depth,
        xyz_camera_m=xyz,
    )

    with pytest.raises(RecordingError, match="content"):
        read_frame_bundle(tmp_path)


def test_same_frame_has_same_content_id(
    tmp_path: Path,
    rgbd_frame: RgbdFrame,
) -> None:
    first = write_frame_bundle(tmp_path / "one", rgbd_frame)
    second = write_frame_bundle(tmp_path / "two", rgbd_frame)

    assert first == second
