from __future__ import annotations

import json

import numpy as np

from vision.calibration_gate import audit_handeye_calibration
from vision.camera_models import PinholeCamera, SeucmCamera
from vision.dual_camera import (
    DualCameraCalibrationBundle,
    DualCameraConfig,
    DualCameraPerception,
    StampedRobotPose,
)
from vision.identity import PersistentIdentityConfig, PersistentIdentityMemory
from vision.instance_pose import InstancePoseConfig
from vision.online_frames import CameraRoleMap, FramePair, RgbFrame
from vision.types import FrameStamp
from vision_models.contracts import InstanceDetection, ModelContractError
from vision.active_view_types import ObservationMoveProposal
from vision_models.active_view_online import (
    ActiveViewEvaluationBatch,
    ActiveViewTargetReport,
)
from vision_models.online import OnlinePerceptionEngine, OnlineVisionConfig, render_overlay


class FakeSegmenter:
    def __init__(self, detections=(), error: Exception | None = None):
        self.detections = tuple(detections)
        self.error = error
        self.calls = 0

    def predict(self, image_rgb):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.detections


class FakeEncoder:
    def __init__(self):
        self.calls = 0

    def encode(self, image_rgb, masks):
        self.calls += 1
        return tuple(np.array([1.0, 0.0, 0.0]) for _ in masks)


def roles() -> CameraRoleMap:
    return CameraRoleMap("lumos_rgb", "d435_depth", "d435_rgb", "cross_camera")


def identity_config() -> PersistentIdentityConfig:
    return PersistentIdentityConfig(
        max_cosine_distance=0.40,
        ambiguity_margin=0.03,
        appearance_weight=0.80,
        position_weight=0.20,
        max_position_distance_m=0.20,
        position_gate_max_age_ns=500_000_000,
        occluded_after_ns=300_000_000,
        inactive_after_ns=1_500_000_000,
        min_confirmed_hits=2,
        min_memory_confidence=0.80,
        min_memory_visibility=0.50,
        work_bank_size=4,
        stable_bank_size=4,
        max_identities=8,
        reacquire_confirmed_hits=2,
        max_actionable_position_std_m=0.025,
        max_actionable_pose_age_ns=200_000_000,
        min_actionable_pose_hits=2,
    )


def detection() -> InstanceDetection:
    mask = np.zeros((5, 5), dtype=bool)
    mask[1:4, 1:4] = True
    return InstanceDetection(
        detection_id=7,
        label="bottle",
        score=0.95,
        bbox_xyxy=np.array([1.0, 1.0, 4.0, 4.0]),
        mask=mask,
    )


def pair(frame_id: int = 1, timestamp_ns: int = 1_000_000_000) -> FramePair:
    image = np.zeros((5, 5, 3), dtype=np.uint8)
    image[1:4, 1:4, 1] = 255
    rgb = RgbFrame(FrameStamp("lumos_rgb", frame_id, timestamp_ns), image)
    return FramePair(rgb, None, timestamp_ns, None, ("depth_unavailable",))


def config() -> OnlineVisionConfig:
    fusion = perception().config
    return OnlineVisionConfig(
        roles=roles(),
        detector_backend="rtmdet_tiny_ins",
        detector_config_path=None,
        detector_checkpoint_path=None,
        detector_labels=("bottle",),
        descriptor_model_id="facebook/dinov2-small",
        detector_device="cuda:0",
        descriptor_device="cuda:0",
        detector_min_score=0.35,
        dino_max_long_side=640,
        min_patch_coverage=0.10,
        task_checkpoint_validated=False,
        latest_only=True,
        max_pending_frames=1,
        max_targets_per_frame=256,
        latency_p95_limit_ms=300.0,
        gpu_memory_limit_gib=7.2,
        robot_execution_enabled=False,
        identity_config=identity_config(),
        perception_config=fusion,
    )


def perception() -> DualCameraPerception:
    return DualCameraPerception(
        PersistentIdentityMemory(identity_config()),
        DualCameraConfig(
            max_frame_skew_ns=50_000_000,
            max_frame_age_ns=200_000_000,
            max_robot_pose_skew_ns=50_000_000,
            min_depth_m=0.10,
            max_depth_m=2.0,
            pose=InstancePoseConfig(4, 0, 3.5, 0.002),
            roles=roles(),
        ),
    )


def engine(detections=(None,), error=None, active_view=None) -> OnlinePerceptionEngine:
    selected = (detection(),) if detections == (None,) else detections
    return OnlinePerceptionEngine(
        FakeSegmenter(selected, error=error),
        FakeEncoder(),
        perception(),
        config(),
        active_view=active_view,
    )


def test_engine_uses_lumos_identity_and_rejects_missing_geometry_and_task_checkpoint():
    result = engine().process(
        pair(),
        robot_pose=None,
        calibration=None,
        arm_stationary=True,
        now_ns=1_020_000_000,
    )

    target = result.targets[0]
    assert result.canonical_rgb_source == "lumos_rgb"
    assert result.metric_depth_source == "d435_depth"
    assert target.identity_id == 1
    assert target.actionable is False
    assert "calibration_unavailable" in target.reasons
    assert "task_checkpoint_unvalidated" in target.reasons
    assert result.model_ready is True


def test_second_frame_confirms_same_identity_but_execution_stays_locked():
    online = engine()
    first = online.process(pair(1, 1_000_000_000), None, None, True, 1_010_000_000)
    second = online.process(pair(2, 1_100_000_000), None, None, True, 1_110_000_000)

    assert first.targets[0].identity_id == second.targets[0].identity_id == 1
    assert second.targets[0].identity_status.value == "confirmed"
    assert second.targets[0].actionable is False
    assert second.robot_execution_enabled is False
    assert second.targets[0].identity_hits == 2
    assert second.targets[0].work_prototype_count == 2
    assert second.targets[0].stable_prototype_count == 1
    assert second.targets[0].appearance_similarity == 1.0
    assert second.targets[0].association_cost == 0.0
    identity = second.to_event()["targets"][0]["identity_memory"]
    assert identity == {
        "hits": 2,
        "work_prototype_count": 2,
        "stable_prototype_count": 1,
        "appearance_similarity": 1.0,
        "association_cost": 0.0,
        "association_reason": None,
    }


def test_empty_detections_skip_encoder_and_serialize_as_empty_targets():
    segmenter = FakeSegmenter(())
    encoder = FakeEncoder()
    online = OnlinePerceptionEngine(segmenter, encoder, perception(), config())

    result = online.process(pair(), None, None, True, 1_010_000_000)

    assert result.targets == ()
    assert encoder.calls == 0
    assert result.to_event()["targets"] == []


def test_model_error_is_reported_without_stale_targets_or_actionability():
    online = engine(error=ModelContractError("synthetic detector failure"))

    result = online.process(pair(), None, None, True, 1_010_000_000)

    assert result.model_ready is False
    assert result.targets == ()
    assert result.model_error == "synthetic detector failure"
    assert "model_unavailable" in result.blockers
    assert result.to_event()["robot_execution_enabled"] is False


def test_latency_history_is_bounded_to_256_and_reports_p95(monkeypatch):
    online = engine(detections=())
    ticks = iter(
        tick
        for index in range(300)
        for tick in (10_000_000_000, 10_000_000_000 + index * 1_000_000)
    )
    monkeypatch.setattr("vision_models.online.time.perf_counter_ns", lambda: next(ticks))

    for index in range(300):
        timestamp_ns = 1_000_000_000 + index * 1_000_000
        result = online.process(
            pair(index + 1, timestamp_ns),
            None,
            None,
            True,
            timestamp_ns,
        )

    assert online.latency_sample_count == 256
    assert 285.0 < result.latency_p95_ms < 288.0


def test_overlay_keeps_native_dimensions_and_event_contains_plain_finite_json():
    source = pair().rgb.image_rgb
    result = engine().process(pair(), None, None, True, 1_010_000_000)

    overlay = render_overlay(source, result)
    payload = result.to_event()

    assert overlay.shape == source.shape
    assert overlay.dtype == np.uint8
    assert not np.shares_memory(overlay, source)
    assert not np.array_equal(overlay[2, 2], source[2, 2])
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert payload["targets"][0]["identity_id"] == 1
    assert payload["canonical_rgb_source"] == "lumos_rgb"


class SyntheticActiveView:
    def evaluate(self, **kwargs):
        target = kwargs["targets"][0]
        return (
            ActiveViewTargetReport(
                detection_id=target.detection_id,
                identity_id=target.identity_id,
                kind="coarse_pose",
                target_pose_id="table_left",
                expires_ns=1_200_000_000,
                coarse_center_xy_m=np.array([0.2, -0.1]),
                valid_depth_points=0,
                central_fraction=None,
                depth_acceptable=False,
                reasons=(),
                active_view_execution_enabled=False,
            ),
        )


class BrokenActiveView:
    def evaluate(self, **_kwargs):
        raise ModelContractError("synthetic active-view failure")


def test_online_event_contains_bounded_nonexecuting_active_view_report() -> None:
    result = engine(active_view=SyntheticActiveView()).process(
        pair(),
        robot_pose=None,
        calibration=None,
        arm_stationary=True,
        now_ns=1_020_000_000,
    )
    payload = result.to_event()
    report = payload["active_view_reports"][0]

    assert report["identity_id"] == payload["targets"][0]["identity_id"]
    assert report["active_view_execution_enabled"] is False
    assert report["target_pose_id"] == "table_left"
    encoded = json.dumps(report).lower()
    for forbidden in ("move_l", "move_joint", "trajectory", "gripper", "can"):
        assert forbidden not in encoded


def test_active_view_adapter_error_does_not_make_model_unavailable() -> None:
    result = engine(active_view=BrokenActiveView()).process(
        pair(),
        robot_pose=None,
        calibration=None,
        arm_stationary=True,
        now_ns=1_020_000_000,
    )

    assert result.model_ready is True
    assert len(result.targets) == 1
    assert result.active_view_reports[0].reasons == ("active_view_adapter_unavailable",)
    assert "active_view_adapter_unavailable" in result.blockers


class RecordingActiveView:
    def __init__(self):
        self.kwargs = None

    def evaluate(self, **kwargs):
        self.kwargs = kwargs
        return ()


def test_online_engine_forwards_verified_stationarity_and_calibration() -> None:
    recorder = RecordingActiveView()
    calibration = DualCameraCalibrationBundle.from_audits(
        d435=PinholeCamera(40.0, 40.0, 2.0, 2.0, 5, 5),
        lumos=SeucmCamera(40.0, 40.0, 2.0, 2.0, 0.5, 1.0, 5, 5),
        d435_to_lumos_audit=audit_handeye_calibration(
            {
                "T_lumos_from_d435": np.eye(4).tolist(),
                "validation": {"reprojection_rmse_px": 0.4, "position_rmse_m": 0.004},
            },
            "T_lumos_from_d435",
        ),
        lumos_to_flange_audit=audit_handeye_calibration(
            {
                "T_flange_from_lumos": np.eye(4).tolist(),
                "validation": {"reprojection_rmse_px": 0.4, "position_rmse_m": 0.004},
            },
            "T_flange_from_lumos",
        ),
    )
    robot_pose = StampedRobotPose(
        FrameStamp("robot_flange_pose", 1, 1_000_000_000),
        np.eye(4),
    )

    engine(active_view=recorder).process(
        pair(),
        robot_pose=robot_pose,
        calibration=calibration,
        arm_stationary=True,
        now_ns=1_020_000_000,
    )

    assert recorder.kwargs is not None
    assert recorder.kwargs["robot_pose"] is robot_pose
    assert recorder.kwargs["calibration"] is calibration
    assert recorder.kwargs["arm_stationary"] is True


class ProposalActiveView:
    def evaluate(self, **_kwargs):
        raise AssertionError("engine must use the trusted batch interface")

    def evaluate_with_proposals(self, **kwargs):
        target = kwargs["targets"][0]
        proposal = ObservationMoveProposal.coarse(
            identity_id=target.identity_id,
            source_stamp=kwargs["rgb_stamp"],
            expires_ns=kwargs["now_ns"] + 100_000_000,
            target_pose_id="table_left",
            joints_deg=[1, 20, -40, 0, 10, 0],
            evidence_ids=("sha256:" + "a" * 64,),
        )
        report = ActiveViewTargetReport(
            detection_id=target.detection_id,
            identity_id=target.identity_id,
            kind="coarse_pose",
            target_pose_id="table_left",
            expires_ns=proposal.expires_ns,
            coarse_center_xy_m=np.array([0.2, -0.1]),
            valid_depth_points=0,
            central_fraction=None,
            depth_acceptable=False,
            reasons=(),
            active_view_execution_enabled=False,
        )
        return ActiveViewEvaluationBatch((report,), (proposal,))


def test_online_result_keeps_trusted_proposals_inside_python_boundary() -> None:
    result = engine(active_view=ProposalActiveView()).process(
        pair(),
        robot_pose=None,
        calibration=None,
        arm_stationary=True,
        now_ns=1_020_000_000,
        current_joints_deg=np.array([1, 20, -40, 0, 10, 0]),
    )

    assert len(result.active_view_proposals) == 1
    assert result.active_view_proposals[0].target_pose_id == "table_left"
    event = result.to_event()
    assert "active_view_proposals" not in event
    assert "joints_deg" not in json.dumps(event)
