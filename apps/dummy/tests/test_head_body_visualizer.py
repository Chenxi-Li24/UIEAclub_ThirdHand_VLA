import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.head_body_visualizer import render_head_body_overlay
from dummy.tracker import Target


def test_overlay_draws_target_and_motion_text_without_resizing_frame():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target = Target(True, 500, 180, 640, 480, 0.9, "mediapipe_face", 1.0)
    command = [0, 0, -4, 33.6, -0.4, 0]
    joints = [0, 0, -4, 33, 0, 0.2]

    rendered = render_head_body_overlay(
        frame,
        target,
        command,
        joints,
        error=None,
        enabled=False,
        robot_url="ws://127.0.0.1:3000/ws",
    )

    assert rendered.shape == frame.shape
    assert int(rendered.sum()) > 0


def test_overlay_draws_rejected_detector_candidate_debug():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target = Target(False, w=640, h=480, kind="none", ts=1.0)

    rendered = render_head_body_overlay(
        frame,
        target,
        [0, 0, -4, 33, 0, 0],
        [0, 0, -4, 33, 0, 0],
        debug={
            "bbox": (90, 30, 120, 120),
            "raw_target": (150, 90),
            "rejected": "mediapipe_far_from_lock",
        },
    )

    assert rendered.shape == frame.shape
    assert int(rendered[30:150, 90:210].sum()) > 0


def test_overlay_draws_mink_virtual3d_control_state():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    target = Target(True, 320, 220, 640, 480, 0.9, "person_lock_virtual3d", 1.0)

    rendered = render_head_body_overlay(
        frame,
        target,
        [1, -4, -5, -5, 0, 1],
        [0, 0, 0, 0, 0, 0],
        debug={
            "control_source": "mink/base/virtual3d/depth_invalid_far_reach",
            "control_backend": "mink",
            "target_3d_mode": "virtual3d",
            "distance_state": "depth_invalid_far_reach",
            "target_xyz_m": [-0.2, -0.05, 1.5],
            "distance_depth_m": 1.5,
            "distance_depth_valid": False,
        },
    )

    assert rendered.shape == frame.shape
    assert int(rendered[420:479, 0:640].sum()) > 0
    assert int(rendered[180:320, 390:640].sum()) > 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("HEAD_BODY_VISUALIZER_OK")
