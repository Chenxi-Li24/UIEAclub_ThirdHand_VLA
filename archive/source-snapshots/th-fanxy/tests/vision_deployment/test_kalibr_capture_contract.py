from __future__ import annotations

import ast
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

SCRIPT = Path(__file__).parents[2] / "scripts/vision/capture_kalibr_dataset.py"


def _load_module():
    namespace: dict[str, object] = {
        "__name__": "capture_kalibr_dataset_contract",
        "__file__": str(SCRIPT),
    }
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), namespace)
    return namespace


def _jpeg(colour: tuple[int, int, int]) -> bytes:
    image = np.zeros((12, 16, 3), dtype=np.uint8)
    image[:] = colour
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return encoded.tobytes()


def test_extract_first_jpeg_accepts_snapshot_and_multipart_stream() -> None:
    module = _load_module()
    extract = module["extract_first_jpeg"]
    jpeg = _jpeg((10, 20, 30))
    multipart = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    assert extract(jpeg) == jpeg
    assert extract(b"noise" + multipart + b"trailing") == jpeg
    with pytest.raises(ValueError, match="JPEG"):
        extract(b"not an image")


def test_write_pair_creates_official_cam0_cam1_timestamp_layout(tmp_path: Path) -> None:
    module = _load_module()
    write_pair = module["write_pair"]
    record = write_pair(
        tmp_path,
        lumos_timestamp_ns=1000000001,
        d435_timestamp_ns=1000000123,
        lumos_jpeg=_jpeg((0, 0, 255)),
        d435_jpeg=_jpeg((0, 255, 0)),
    )

    assert (tmp_path / "cam0/1000000001.png").is_file()
    assert (tmp_path / "cam1/1000000123.png").is_file()
    assert record == {
        "lumos_timestamp_ns": 1000000001,
        "d435_timestamp_ns": 1000000123,
        "capture_skew_ns": 122,
    }
    assert list(tmp_path.rglob("*.tmp")) == []


def test_manifest_is_content_addressed_and_records_kalibr_model_order(tmp_path: Path) -> None:
    module = _load_module()
    write_manifest = module["write_manifest"]
    output = write_manifest(
        tmp_path,
        [{"lumos_timestamp_ns": 1, "d435_timestamp_ns": 2, "capture_skew_ns": 1}],
        lumos_url="http://127.0.0.1:3001/frame.jpg",
        d435_url="http://127.0.0.1:3100/camera_d435_raw",
        purpose="fit",
    )
    manifest = json.loads(output.read_text(encoding="utf-8"))

    assert manifest["content_id"].startswith("sha256:")
    assert manifest["kalibr_topics"] == ["/cam0/image_raw", "/cam1/image_raw"]
    assert manifest["kalibr_models"] == ["eucm-none", "pinhole-none"]
    assert manifest["purpose"] == "fit"
    assert manifest["robot_or_motion_access"] is False


def test_capture_script_import_graph_has_no_robot_or_camera_sdk() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)

    assert not any("startouch" in name.lower() for name in imports)
    assert not any("pyrealsense" in name.lower() for name in imports)
    assert "move_" not in source
