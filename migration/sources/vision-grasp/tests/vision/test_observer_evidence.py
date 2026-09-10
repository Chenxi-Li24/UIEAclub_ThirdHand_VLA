from __future__ import annotations

import json

import numpy as np

from thirdhand_va.common.contracts import MaskCandidate, RgbdFrame
from thirdhand_va.vision.observer_evidence import (
    save_projection_failure_evidence,
    should_capture_projection_failure,
)


def _scene():
    rgb = np.zeros((40, 60, 3), dtype=np.uint8)
    rgb[..., 1] = 30
    mask = np.zeros((40, 60), dtype=bool)
    mask[10:31, 20:41] = True
    xyz = np.full((40, 60, 3), np.nan, dtype=np.float32)
    frame = RgbdFrame(
        sequence=1336,
        monotonic_ns=5_000_000_000,
        camera_serial="camera",
        rgb=rgb,
        depth_m=xyz[..., 2],
        xyz_camera_m=xyz,
    )
    candidate = MaskCandidate(
        detection_id=0,
        label="bottle",
        score=0.6978,
        bbox_xyxy=(20, 10, 41, 31),
        mask=mask,
        authorized=True,
        descriptor=np.ones(4, dtype=np.float32),
    )
    payload = {
        "event": "bottle_projection_guard",
        "frame_id": 1336,
        "target_id": "detection:0",
        "observed_at_ms": 1_000,
        "emitted_at_ms": 1_110,
        "rgb_observation_valid": True,
        "projection_guard_valid": False,
        "robot_pose_blockers": [],
        "guard_blockers": ["projected_width_mismatch"],
        "pixel_uv": [32.0, 22.0],
        "diagnostics": {"width_ratio": 1.1557},
    }
    return frame, candidate, payload


def test_capture_trigger_requires_stationary_rgb_valid_projection_failure() -> None:
    _frame, candidate, payload = _scene()

    assert should_capture_projection_failure(payload, candidate)
    for change in ("pose", "expired", "rgb", "passed", "lost"):
        changed = dict(payload)
        current_candidate = candidate
        if change == "pose":
            changed["robot_pose_blockers"] = ["pose_not_stationary"]
        elif change == "expired":
            changed["guard_blockers"] = ["anchor_expired"]
        elif change == "rgb":
            changed["rgb_observation_valid"] = False
        elif change == "passed":
            changed["projection_guard_valid"] = True
        else:
            current_candidate = None
        assert not should_capture_projection_failure(changed, current_candidate)


def test_save_writes_overlay_rgb_frame_mask_and_timed_metadata(tmp_path) -> None:
    frame, candidate, payload = _scene()
    overlay = tmp_path / "side-view-failure.jpg"

    result = save_projection_failure_evidence(
        overlay,
        frame=frame,
        candidate=candidate,
        payload=payload,
        write_started_at_ms=1_120,
        write_completed_at_ms=lambda: 1_135,
    )

    assert overlay.is_file()
    assert (tmp_path / "side-view-failure.rgb.png").is_file()
    arrays = np.load(tmp_path / "side-view-failure.frame-mask.npz")
    np.testing.assert_array_equal(arrays["rgb"], frame.rgb)
    np.testing.assert_array_equal(arrays["mask"], candidate.mask)
    metadata = json.loads(
        (tmp_path / "side-view-failure.metadata.json").read_text()
    )
    assert metadata["write_started_at_ms"] == 1_120
    assert metadata["write_completed_at_ms"] == 1_135
    assert metadata["payload_emitted_at_ms"] == 1_110
    assert metadata["write_after_payload_emitted"] is True
    assert metadata["projection_payload"]["guard_blockers"] == [
        "projected_width_mismatch"
    ]
    assert result["overlay_path"] == str(overlay.resolve())
    assert result["frame_mask_path"].endswith("side-view-failure.frame-mask.npz")
