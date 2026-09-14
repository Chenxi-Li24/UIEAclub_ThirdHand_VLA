import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from thirdhand_va.vision.camera.recording import write_frame_bundle

from test_grasp_pose import make_scene


ROOT = Path(__file__).resolve().parents[3]


def test_debug_geometry_writes_ranked_json_and_visualization(tmp_path: Path) -> None:
    frame, candidate, _config = make_scene()
    bundle = tmp_path / "bundle"
    mask_path = tmp_path / "mask.npy"
    output_json = tmp_path / "geometry.json"
    output_image = tmp_path / "geometry.jpg"
    write_frame_bundle(bundle, frame)
    np.save(mask_path, candidate.mask)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/vision/debug_geometry.py",
            str(bundle),
            str(mask_path),
            "--output-json",
            str(output_json),
            "--output-image",
            str(output_image),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert len(payload["candidates"]) >= 2
    assert payload["candidates"][0]["height_fraction"] == 0.5
    assert len(payload["table_normal"]) == 3
    assert payload["robot_control_enabled"] is False
    assert cv2.imread(str(output_image)) is not None
