import numpy as np
import pytest

from thirdhand_va.vision.visualization import encode_jpeg
from thirdhand_va.vision.visualization.preview_status import (
    render_offline_frame,
    render_preview_banner,
)


def test_preview_banner_is_visible_and_does_not_mutate_input() -> None:
    rgb = np.full((120, 240, 3), 80, dtype=np.uint8)
    original = rgb.copy()

    rendered = render_preview_banner(
        rgb,
        title="VISION OFFLINE - RAW CAMERA",
        detail="retrying fused stream",
    )

    assert np.array_equal(rgb, original)
    assert rendered.shape == rgb.shape
    assert np.any(rendered[:60] != original[:60])
    assert np.array_equal(rendered[80:], original[80:])
    assert encode_jpeg(rendered).startswith(b"\xff\xd8")


def test_offline_frame_has_requested_shape_and_visible_content() -> None:
    rendered = render_offline_frame(320, 240, "no camera stream")

    assert rendered.shape == (240, 320, 3)
    assert rendered.dtype == np.uint8
    assert np.any(rendered != 0)
    assert np.unique(rendered.reshape(-1, 3), axis=0).shape[0] > 3


def test_preview_status_rejects_invalid_images_and_dimensions() -> None:
    with pytest.raises(ValueError, match="uint8 RGB"):
        render_preview_banner(
            np.zeros((10, 10), dtype=np.uint8),
            title="offline",
            detail="invalid",
        )
    with pytest.raises(ValueError, match="width and height"):
        render_offline_frame(20, 20, "too small")
