import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.follow3d.target_projector import Virtual3DTargetProjector
from dummy.tracker import Target


def test_projector_clamps_far_gaze_depth_to_virtual_point():
    projector = Virtual3DTargetProjector({
        "virtual_3d_target": {
            "focal_px": 500.0,
            "max_gaze_depth_m": 1.8,
            "smoothing_alpha": 1.0,
        },
        "vision": {"frame_w": 640, "frame_h": 480},
    })
    target = Target(True, 420, 240, 640, 480, 0.9, "person", 1.0)

    virtualized = projector.ensure_xyz(target, depth_hint_m=4.0)

    assert virtualized
    assert round(target.xyz_m[2], 2) == 1.80
    assert round(target.xyz_m[0], 2) == 0.36


def test_projector_keeps_near_depth_for_close_spacing():
    projector = Virtual3DTargetProjector({
        "virtual_3d_target": {
            "focal_px": 500.0,
            "max_gaze_depth_m": 1.8,
            "smoothing_alpha": 1.0,
        },
        "vision": {"frame_w": 640, "frame_h": 480},
    })
    target = Target(True, 320, 240, 640, 480, 0.9, "person", 1.0)

    projector.ensure_xyz(target, depth_hint_m=0.30)

    assert target.xyz_m == [0.0, 0.0, 0.30]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("VIRTUAL_3D_TARGET_PROJECTOR_OK")
