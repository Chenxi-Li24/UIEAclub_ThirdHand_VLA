from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from thirdhand_vision import (
    FrameStamp as SdkFrameStamp,
)
from thirdhand_vision import (
    InstanceDetection as SdkDetection,
)
from thirdhand_vision import (
    PerceptionInstance,
    PerceptionResult,
)
from thirdhand_vision import (
    PoseEstimate as SdkPose,
)
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.online_frames import DepthFrame, FramePair, RgbFrame
from vision.types import CalibrationRef, FrameStamp
from vision_sdk_adapter import (
    compare_replay_frames,
    frame_pair_to_sdk,
    runtime_calibration_to_sdk,
    sdk_result_to_detection_event,
)

CALIBRATION_ID = f"sha256:{'b' * 64}"


def make_pair() -> FramePair:
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[1, 2] = [20, 40, 60]
    depth = np.full((3, 5), 0.8, dtype=float)
    depth[0, 0] = 0.0
    return FramePair(
        rgb=RgbFrame(FrameStamp("lumos_rgb", 42, 9_000_000), rgb),
        depth=DepthFrame(FrameStamp("d435_depth", 18, 8_900_000), depth),
        fusion_monotonic_ns=9_000_000,
        frame_skew_ns=100_000,
        reasons=(),
    )


def make_runtime_calibration() -> SimpleNamespace:
    return SimpleNamespace(
        d435=PinholeCamera(fx=500, fy=501, cx=2, cy=1, width=5, height=3),
        lumos=SeucmCamera(
            fx=300, fy=301, cx=3, cy=2, alpha=0.55, beta=1.1, width=6, height=4
        ),
        t_lumos_from_d435=np.eye(4),
        calibration=CalibrationRef(
            calibration_id=CALIBRATION_ID,
            validated=True,
            reprojection_rmse_px=0.42,
        ),
    )


def make_sdk_result(identity_id: int = 12) -> PerceptionResult:
    mask = np.zeros((4, 6), dtype=np.bool_)
    mask[1:3, 2:5] = True
    detection = SdkDetection(
        detection_id=3,
        label="bottle",
        score=0.94,
        bbox_xyxy=np.array([2, 1, 5, 3], dtype=float),
        mask=mask,
        image_shape=(4, 6),
    )
    stamp = SdkFrameStamp("fusion", 42, 9_000_000)
    pose = SdkPose(
        xyz_m=np.array([0.31, -0.08, 0.04]),
        covariance_m2=np.diag([4e-6, 9e-6, 16e-6]),
        frame="robot_base",
        stamp=stamp,
        calibration_id=CALIBRATION_ID,
    )
    instance = PerceptionInstance(
        detection=detection,
        identity_id=identity_id,
        identity_status="confirmed",
        descriptor=np.array([0.6, 0.8]),
        pose=pose,
        reasons=("physical_grasp_execution_locked",),
        annotations={
            "registered_depth_points": 184,
            "identity_memory": {
                "hits": 5,
                "work_prototype_count": 4,
                "stable_prototype_count": 3,
                "appearance_similarity": 0.93,
                "association_cost": 0.07,
                "association_reason": None,
            },
        },
    )
    return PerceptionResult(
        frame_id=42,
        monotonic_ns=9_000_000,
        instances=(instance,),
        blockers=("calibration_unavailable",),
    )


def make_parity_event(
    *, frame_id: int = 42, detection_id: int = 3, identity_id: int = 12
) -> dict:
    event = sdk_result_to_detection_event(make_sdk_result(identity_id), ts_ms=1000)
    event["frame_id"] = frame_id
    event["targets"][0]["detection_id"] = detection_id
    event["targets"][0]["correspondence_id"] = "physical-object:coke-1"
    event["targets"][0]["descriptor"] = [0.6, 0.8]
    return event


def test_frame_pair_conversion_preserves_roles_stamps_and_immutable_arrays() -> None:
    calibration = runtime_calibration_to_sdk(
        make_runtime_calibration(), t_output_from_lumos=np.eye(4)
    )
    bundle = frame_pair_to_sdk(
        make_pair(),
        calibration,
        canonical_rgb_source="lumos_rgb",
        metric_depth_source="d435_depth",
    )

    assert bundle.stamp == SdkFrameStamp("lumos_rgb", 42, 9_000_000)
    assert bundle.depth_stamp == SdkFrameStamp("d435_depth", 18, 8_900_000)
    assert bundle.metadata == {
        "fusion_monotonic_ns": 9_000_000,
        "frame_skew_ns": 100_000,
        "reasons": (),
    }
    assert np.isnan(bundle.depth_m[0, 0])
    assert bundle.rgb.flags.writeable is False
    assert bundle.depth_m.flags.writeable is False
    assert calibration.ref.calibration_id == CALIBRATION_ID
    assert calibration.ref.validated is True
    assert calibration.ref.reprojection_rmse_px == 0.42


def test_frame_pair_conversion_rejects_infinite_depth() -> None:
    pair = make_pair()
    unsafe_depth = np.array(pair.depth.depth_z_m, copy=True)
    unsafe_depth[0, 0] = np.inf
    unsafe_pair = SimpleNamespace(
        rgb=pair.rgb,
        depth=SimpleNamespace(stamp=pair.depth.stamp, depth_z_m=unsafe_depth),
        fusion_monotonic_ns=pair.fusion_monotonic_ns,
        frame_skew_ns=pair.frame_skew_ns,
        reasons=pair.reasons,
    )

    with pytest.raises(ValueError, match="depth image cannot contain infinity"):
        frame_pair_to_sdk(
            unsafe_pair,
            None,
            canonical_rgb_source="lumos_rgb",
            metric_depth_source="d435_depth",
        )


def test_frame_pair_conversion_rejects_source_relabeling_and_calibration_size_mismatch() -> None:
    pair = make_pair()
    calibration = runtime_calibration_to_sdk(
        make_runtime_calibration(), t_output_from_lumos=np.eye(4)
    )
    spoofed_rgb = SimpleNamespace(
        stamp=FrameStamp("untrusted_rgb", 42, 9_000_000),
        image_rgb=pair.rgb.image_rgb,
    )
    with pytest.raises(ValueError, match="canonical RGB source"):
        frame_pair_to_sdk(
            SimpleNamespace(**{**pair.__dict__, "rgb": spoofed_rgb}),
            calibration,
            canonical_rgb_source="lumos_rgb",
            metric_depth_source="d435_depth",
        )

    wrong_rgb = SimpleNamespace(
        stamp=pair.rgb.stamp,
        image_rgb=np.zeros((5, 6, 3), dtype=np.uint8),
    )
    with pytest.raises(ValueError, match="Lumos calibration dimensions"):
        frame_pair_to_sdk(
            SimpleNamespace(**{**pair.__dict__, "rgb": wrong_rgb}),
            calibration,
            canonical_rgb_source="lumos_rgb",
            metric_depth_source="d435_depth",
        )

    wrong_depth = SimpleNamespace(
        stamp=pair.depth.stamp,
        depth_z_m=np.ones((4, 5), dtype=float),
    )
    with pytest.raises(ValueError, match="D435 calibration dimensions"):
        frame_pair_to_sdk(
            SimpleNamespace(**{**pair.__dict__, "depth": wrong_depth}),
            calibration,
            canonical_rgb_source="lumos_rgb",
            metric_depth_source="d435_depth",
        )


def test_sdk_result_serializes_existing_event_without_actionability() -> None:
    event = sdk_result_to_detection_event(make_sdk_result(), ts_ms=1_700_000_000_000)

    assert event["type"] == "detection_result"
    assert event["frame_id"] == 42
    assert event["monotonic_ns"] == 9_000_000
    assert event["targets"][0] == {
        "detection_id": 3,
        "identity_id": 12,
        "identity_status": "confirmed",
        "identity_memory": {
            "hits": 5,
            "work_prototype_count": 4,
            "stable_prototype_count": 3,
            "appearance_similarity": 0.93,
            "association_cost": 0.07,
            "association_reason": None,
        },
        "label": "bottle",
        "score": 0.94,
        "bbox_xyxy": [2.0, 1.0, 5.0, 3.0],
        "pose": {
            "xyz_m": [0.31, -0.08, 0.04],
            "covariance_m2": [[4e-06, 0.0, 0.0], [0.0, 9e-06, 0.0], [0.0, 0.0, 1.6e-05]],
            "frame": "robot_base",
            "frame_id": 42,
            "monotonic_ns": 9_000_000,
            "calibration_id": CALIBRATION_ID,
        },
        "registered_depth_points": 184,
        "actionable": False,
        "reasons": ["physical_grasp_execution_locked"],
    }
    assert event["blockers"] == ["calibration_unavailable"]
    assert event["robot_execution_enabled"] is False
    assert event["active_view_execution_enabled"] is False
    encoded = json.dumps(event, allow_nan=False)
    assert "descriptor" not in encoded
    assert "mask" not in encoded


def test_replay_comparator_fails_when_declared_pose_threshold_is_exceeded() -> None:
    legacy = [make_parity_event()]
    sdk = json.loads(json.dumps(legacy))
    sdk[0]["targets"][0]["pose"]["xyz_m"][0] += 0.010
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    report = compare_replay_frames(legacy, sdk, thresholds)

    assert report["passed"] is False
    assert report["metrics"]["paired_frames"] == 1
    assert report["metrics"]["pose_rmse_m"] == pytest.approx(0.01 / np.sqrt(3))
    assert "pose_rmse_m_max" in report["failures"]


def test_replay_comparator_accepts_exact_replay() -> None:
    legacy = [make_parity_event()]
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    report = compare_replay_frames(legacy, json.loads(json.dumps(legacy)), thresholds)

    assert report == {
        "schema_version": 1,
        "metrics": {
            "paired_frames": 1,
            "detection_count_mismatches": 0,
            "label_mismatches": 0,
            "blocker_mismatches": 0,
            "identity_switch_delta": 0,
            "pose_rmse_m": 0.0,
            "covariance_abs_max": 0.0,
            "descriptor_pairs": 1,
            "descriptor_cosine_delta": 0.0,
        },
        "failures": [],
        "passed": True,
    }


def test_replay_comparator_requires_measured_descriptors_and_persistent_correspondence() -> None:
    legacy = [make_parity_event()]
    sdk = json.loads(json.dumps(legacy))
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    del sdk[0]["targets"][0]["descriptor"]
    with pytest.raises(ValueError, match="descriptors are required"):
        compare_replay_frames(legacy, sdk, thresholds)

    sdk = json.loads(json.dumps(legacy))
    del sdk[0]["targets"][0]["correspondence_id"]
    with pytest.raises(ValueError, match="correspondence_id"):
        compare_replay_frames(legacy, sdk, thresholds)


def test_identity_switch_metric_uses_persistent_correspondence_not_detection_id() -> None:
    legacy = [
        make_parity_event(frame_id=1, detection_id=10, identity_id=12),
        make_parity_event(frame_id=2, detection_id=99, identity_id=12),
    ]
    sdk = json.loads(json.dumps(legacy))
    sdk[1]["targets"][0]["identity_id"] = 15
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    report = compare_replay_frames(legacy, sdk, thresholds)

    assert report["metrics"]["identity_switch_delta"] == 1
    assert "identity_switch_delta_max" in report["failures"]


def test_identity_switch_metric_remembers_correspondence_across_occlusion() -> None:
    hidden = {"frame_id": 2, "targets": [], "blockers": []}
    legacy = [
        make_parity_event(frame_id=1, detection_id=10, identity_id=12),
        hidden,
        make_parity_event(frame_id=3, detection_id=5, identity_id=12),
    ]
    sdk = json.loads(json.dumps(legacy))
    sdk[2]["targets"][0]["identity_id"] = 15
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    report = compare_replay_frames(legacy, sdk, thresholds)

    assert report["metrics"]["identity_switch_delta"] == 1
    assert "identity_switch_delta_max" in report["failures"]


def test_replay_comparator_fails_when_descriptor_coverage_is_zero() -> None:
    empty = [{"frame_id": 1, "targets": [], "blockers": []}]
    thresholds = {
        "identity_switch_delta_max": 0,
        "pose_rmse_m_max": 0.005,
        "covariance_abs_max": 0.0001,
        "descriptor_cosine_delta_max": 0.02,
    }

    report = compare_replay_frames(empty, json.loads(json.dumps(empty)), thresholds)

    assert report["metrics"]["descriptor_pairs"] == 0
    assert report["passed"] is False
    assert "descriptor_pairs_missing" in report["failures"]


def test_replay_parity_cli_writes_canonical_report(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    event = make_parity_event()
    legacy_path = tmp_path / "legacy.jsonl"
    sdk_path = tmp_path / "sdk.jsonl"
    output_path = tmp_path / "report.json"
    line = json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n"
    legacy_path.write_text(line, encoding="utf-8")
    sdk_path.write_text(line, encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(root / "src"),
            str(root / "packages" / "thirdhand-vision-sdk" / "src"),
            str(root / "web-control" / "server"),
        ]
    )

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "vision" / "run_sdk_replay_parity.py"),
            "--legacy",
            str(legacy_path),
            "--sdk",
            str(sdk_path),
            "--config",
            str(root / "configs" / "vision" / "sdk_replay_parity.yaml"),
            "--output",
            str(output_path),
        ],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    report_text = output_path.read_text(encoding="utf-8")
    assert report_text.endswith("\n")
    assert json.loads(report_text)["passed"] is True
