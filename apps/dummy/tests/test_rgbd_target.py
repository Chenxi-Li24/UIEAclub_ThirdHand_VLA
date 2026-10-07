import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.rgbd_target import RgbdTargetBuilder


def observation(**target_overrides):
    target = {
        "stable_id": 1,
        "label": "person",
        "score": 0.92,
        "bbox_xyxy": [220, 80, 420, 430],
        "centroid_xy": [321.0, 238.0],
        "track_state": "confirmed",
        "depth_valid": True,
        "depth_valid_ratio": 0.42,
        "valid_depth_points": 2400,
        "camera_xyz_m": [0.03, -0.01, 0.78],
        "base_xyz_m": None,
        "base_pose_status": "physical_validation_pending",
        "depth_m": 0.78,
    }
    target.update(target_overrides)
    return {
        "schema": "thirdhand-va-detection-v3",
        "frameId": 42,
        "observedAtMs": 100000,
        "monotonicNs": 123456789,
        "status": "tracking",
        "target": target,
        "targets": [target],
    }


def config():
    return {
        "vision": {"frame_w": 640, "frame_h": 480},
        "rgbd_target": {
            "max_observation_age_s": 0.30,
            "min_depth_ratio": 0.10,
            "min_depth_points": 100,
            "prefer_labels": ["person", "face", "human"],
        },
    }


def test_builds_3d_target_from_valid_person_depth():
    builder = RgbdTargetBuilder(config(), now_ms=lambda: 100050)

    target = builder.from_observation(observation())

    assert target.found
    assert target.kind == "person_depth"
    assert target.u == 321.0
    assert target.v == 238.0
    assert target.xyz_m == [0.03, -0.01, 0.78]
    assert target.depth_valid is True
    assert target.depth_m == 0.78
    assert target.stable_id == 1


def test_invalid_depth_keeps_2d_person_target_without_xyz():
    builder = RgbdTargetBuilder(config(), now_ms=lambda: 100050)

    target = builder.from_observation(observation(depth_valid_ratio=0.01, valid_depth_points=12))

    assert target.found
    assert target.kind == "person_2d"
    assert target.xyz_m is None
    assert target.depth_valid is False


def test_stale_observation_returns_not_found():
    builder = RgbdTargetBuilder(config(), now_ms=lambda: 101000)

    target = builder.from_observation(observation())

    assert not target.found
    assert target.kind == "rgbd_stale"


def test_prefers_person_candidate_over_bottle_when_no_selected_target():
    builder = RgbdTargetBuilder(config(), now_ms=lambda: 100050)
    obs = observation(label="bottle", score=0.99)
    person = dict(obs["targets"][0])
    person.update({"label": "person", "score": 0.60, "centroid_xy": [350.0, 230.0]})
    obs["target"] = None
    obs["targets"] = [obs["targets"][0], person]

    target = builder.from_observation(obs)

    assert target.kind == "person_depth"
    assert target.u == 350.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("RGBD_TARGET_OK")
