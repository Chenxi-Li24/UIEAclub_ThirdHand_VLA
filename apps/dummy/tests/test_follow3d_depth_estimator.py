import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.follow3d.depth_estimator import DepthEstimator
from dummy.tracker import Target


def test_depth_estimator_prefers_rgbd_depth():
    estimator = DepthEstimator({"monocular_depth": {"smoothing_alpha": 1.0, "rgbd_weight": 1.0, "mono_weight": 0.0}})
    target = Target(True, 320, 240, 640, 480, 0.9, "person", 1.0)
    target.depth_valid = True
    target.depth_m = 0.72

    depth = estimator.estimate(target, {"lock_candidate": {"w": 80, "h": 220, "kind": "person"}})

    assert depth.source == "rgbd"
    assert depth.metric is True
    assert round(depth.depth_m, 2) == 0.72


def test_depth_estimator_fuses_rgbd_with_always_on_body_box():
    estimator = DepthEstimator({
        "monocular_depth": {
            "focal_px": 500.0,
            "assumed_body_height_m": 1.6,
            "smoothing_alpha": 1.0,
            "rgbd_weight": 0.75,
            "mono_weight": 0.25,
        }
    })
    target = Target(True, 320, 240, 640, 480, 0.9, "person", 1.0)
    target.depth_valid = True
    target.depth_m = 1.0

    depth = estimator.estimate(target, {"lock_candidate": {"u": 320, "v": 240, "w": 100, "h": 400, "kind": "person"}})

    assert depth.source == "fused"
    assert depth.metric is True
    assert round(depth.depth_m, 2) == 1.25


def test_depth_estimator_uses_body_box_when_rgbd_missing():
    estimator = DepthEstimator({"monocular_depth": {"focal_px": 500.0, "assumed_body_height_m": 1.6, "smoothing_alpha": 1.0}})
    target = Target(True, 320, 240, 640, 480, 0.9, "person_lock", 1.0)

    depth = estimator.estimate(target, {"lock_candidate": {"u": 320, "v": 240, "w": 100, "h": 400, "kind": "person"}})

    assert depth.source == "mono_bbox"
    assert depth.metric is False
    assert round(depth.depth_m, 2) == 2.00


def test_depth_estimator_reports_near_body_as_mono_even_without_rgbd():
    estimator = DepthEstimator({"monocular_depth": {"focal_px": 500.0, "assumed_body_height_m": 1.6, "smoothing_alpha": 1.0}})
    target = Target(True, 320, 240, 640, 480, 0.9, "person_lock", 1.0)

    depth = estimator.estimate(target, {"lock_candidate": {"u": 320, "v": 240, "w": 260, "h": 1200, "kind": "person"}})

    assert depth.source == "mono_bbox"
    assert round(depth.depth_m, 2) == 0.67


def test_depth_estimator_clamps_close_face_box():
    estimator = DepthEstimator({"monocular_depth": {"focal_px": 520.0, "assumed_face_height_m": 0.22, "min_depth_m": 0.45, "smoothing_alpha": 1.0}})
    target = Target(True, 320, 240, 640, 480, 0.9, "face_lock", 1.0)

    depth = estimator.estimate(target, {"lock_candidate": {"u": 320, "v": 240, "w": 260, "h": 400, "kind": "face"}})

    assert depth.source == "mono_bbox"
    assert depth.depth_m == 0.45


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("FOLLOW3D_DEPTH_ESTIMATOR_OK")
