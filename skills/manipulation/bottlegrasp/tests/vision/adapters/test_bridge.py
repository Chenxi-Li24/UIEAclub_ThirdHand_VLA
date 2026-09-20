import hashlib
import io

import numpy as np

from thirdhand_va.vision.adapters import (
    FrameProvenance,
    LatestFramePublisher,
    build_detection_event,
    build_mjpeg_part,
)
from thirdhand_va.common.contracts import MaskCandidate, TrackedBottle, VisionDecision


def decision(frame_id: int = 42) -> VisionDecision:
    mask = np.zeros((20, 30), dtype=bool)
    mask[2:18, 10:20] = True
    target = MaskCandidate(
        detection_id=77,
        label="bottle",
        score=0.88,
        bbox_xyxy=(10, 2, 20, 18),
        mask=mask,
        authorized=True,
    )
    track = TrackedBottle(
        stable_id=2,
        backend_track_id=91,
        state="confirmed",
        candidate=target,
        centroid_xy=(14.5, 9.5),
        depth_supported=False,
        blockers=("depth_insufficient",),
    )
    return VisionDecision(
        status="uncertain",
        frame_id=frame_id,
        target=target,
        pose=None,
        reasons=("depth_insufficient",),
        stable_hits=0,
        window_size=5,
        candidates=(target,),
        request_id="req-2",
        selected_stable_id=2,
        tracks=(track,),
        captured_monotonic_ns=(987654321 if frame_id == 42 else frame_id * 10),
        camera_serial="250801DR48FP25002738",
        registration_id="xvisio-sdk:250801DR48FP25002738",
        motion_epoch=3,
        evidence_id="sha256:" + "a" * 64,
    )


def test_mjpeg_part_contains_exact_provenance_and_integrity_headers() -> None:
    jpeg = b"\xff\xd8example\xff\xd9"
    provenance = FrameProvenance(42, 987654321, 1770000000123)

    part = build_mjpeg_part(jpeg, provenance)

    assert part.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
    assert b"Content-Length: 11\r\n" in part
    assert b"X-ThirdHand-Frame-Id: 42\r\n" in part
    assert b"X-ThirdHand-Monotonic-Ns: 987654321\r\n" in part
    assert b"X-ThirdHand-Observed-At-Ms: 1770000000123\r\n" in part
    assert hashlib.sha256(jpeg).hexdigest().encode() in part
    assert part.endswith(jpeg + b"\r\n")


def test_v3_detection_event_exposes_stable_ids_and_single_lumos_provenance() -> None:
    provenance = FrameProvenance(42, 987654321, 1770000000123)

    event = build_detection_event(
        decision(),
        provenance,
        b"jpeg",
        model_provenance={"backend": "fixture"},
    )

    assert event["schema"] == "thirdhand-va-detection-v3"
    assert event["request_id"] == "req-2"
    assert event["selected_stable_id"] == 2
    assert event["registration_id"] == "xvisio-sdk:250801DR48FP25002738"
    assert event["motion_epoch"] == 3
    assert event["evidence_id"].startswith("sha256:")
    assert event["model_provenance"] == {"backend": "fixture"}
    assert event["targets"] == [{
        "stable_id": 2,
        "backend_track_id": 91,
        "track_state": "confirmed",
        "detection_id": 77,
        "label": "bottle",
        "score": 0.88,
        "bbox_xyxy": [10.0, 2.0, 20.0, 18.0],
        "centroid_xy": [14.5, 9.5],
        "selected": True,
        "depth_valid": False,
        "blockers": ["depth_insufficient"],
    }]
    assert "d435" not in str(event).lower()
    assert "ordinal" not in str(event).lower()
    assert event["robot_control_enabled"] is False


def test_latest_frame_publisher_drops_older_pending_frame() -> None:
    publisher = LatestFramePublisher()
    publisher.offer(b"old", decision(1), FrameProvenance(1, 10, 100))
    publisher.offer(b"new", decision(2), FrameProvenance(2, 20, 200))
    primary, events, overlay = io.BytesIO(), io.BytesIO(), io.BytesIO()

    assert publisher.drain(primary, events, overlay) is True

    assert b"new" in primary.getvalue() and b"old" not in primary.getvalue()
    assert b'"frame_id":2' in events.getvalue()
    assert b"X-ThirdHand-Frame-Id: 2" in overlay.getvalue()
    assert publisher.drain(primary, events, overlay) is False


def test_selected_target_carries_fail_closed_robot_base_preview() -> None:
    preview = {
        "preview_id": "sha256:" + "1" * 64,
        "identity_id": 2,
        "detection_id": 77,
        "frame": "robot_base",
        "calibration_id": "sha256:" + "2" * 64,
        "evidence_ids": ["sha256:" + "3" * 64],
        "grasp_xyz_m": [0.4, 0.0, 0.2],
        "pregrasp_xyz_m": [0.3, 0.0, 0.2],
        "retreat_xyz_m": [0.3, 0.0, 0.2],
        "yaw_rad": 0.0,
        "width_m": 0.06,
        "stable_samples": 3,
        "allowed": False,
        "blockers": ["handeye_physical_validation_pending"],
    }

    event = build_detection_event(
        decision(),
        FrameProvenance(42, 987654321, 1770000000123),
        b"jpeg",
        grasp_preview=preview,
    )

    assert event["targets"][0]["grasp_preview"]["frame"] == "robot_base"
    assert event["targets"][0]["actionable"] is False
