"""A frame must not combine geometry at pose A with displayed coordinates at B."""
import json
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

import numpy as np

import camera_bridge_with_frames as bridge
from handeye_projection_with_frames import HandEyeProjection
from thirdhand_va.common.config import VisionConfig

ROOT = Path(__file__).resolve().parents[3]
STAMP = 1_000_000_000


class GeometrySink:
    """Replace only expensive perception; keep the real bridge and projector."""
    def process(self, frame, **kwargs):
        self.transform = kwargs["t_base_camera"]
        candidate = SimpleNamespace(detection_id=1, mask=np.ones((30, 30), bool))
        return SimpleNamespace(tracks=[SimpleNamespace(candidate=candidate, state="confirmed")])


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="frame-snapshot-test-")
        self.addCleanup(self.temp.cleanup)
        self.calibration = Path(self.temp.name) / "calibration.json"
        self.calibration.write_text(json.dumps({
            "schema": "thirdhand-handeye-calibration-v3",
            "robot_state_semantics": "T_base_flange",
            "extrinsic_semantics": "T_flange_camera",
            "T_flange_camera": {"matrix_4x4": np.eye(4).tolist()},
            "camera": {"camera_serial": "test", "registration_id": "test", "camera_mount_id": "test"},
            "numerically_validated": True,
            "physical_validation": {"status": "pending"},
            "frame_normalization": {"policy_id": "sha256:" + "a" * 64},
        }))
        live = Path(os.environ["THIRDHAND_LIVE_ROOT"])
        self.config = VisionConfig.from_yaml(live / "skills/manipulation/bottlegrasp/configs/vision.yaml")
        self.projection = self.new_projection()
        self.assertTrue(self.projection.update(self.message(), STAMP))
        self.runtime = bridge.UnifiedVisionRuntime(self.config, None, projection=self.projection)
        self.runtime.pipeline = GeometrySink()
        self.frame = self.new_frame()

    def new_projection(self):
        return HandEyeProjection(self.calibration, "test", "test", "test",
            ROOT / "assets/robot/startouch-v3/FastTouchV3.SLDASM.urdf", allow_numerical_only=True)

    def message(self, stamp=STAMP, x=0.1275):
        # Hand-computed URDF zero-joint flange origin; rotation is identity.
        return {"type": "arm_state", "pose_frame": "robot_flange", "connected": True,
            "healthy": True, "stationary": True, "flange_position_m": [x, 0, 0.17605],
            "flange_euler_rad": [0, 0, 0], "joints_deg": [0] * 6,
            "observed_monotonic_ns": stamp,
            "frame_normalization": {"policy_id": "sha256:" + "a" * 64}}

    def new_frame(self, sequence=1, stamp=STAMP):
        return SimpleNamespace(sequence=sequence, monotonic_ns=stamp, camera_serial="test",
            rgb=np.zeros((30, 30, 3), np.uint8), depth_m=np.full((30, 30), 0.4, np.float32),
            xyz_camera_m=np.tile(np.array([0, 0, 0.4], np.float32), (30, 30, 1)))

    def snapshot(self, frame=None):
        method = getattr(self.runtime, "take_projection_snapshot", None)
        self.assertTrue(callable(method), "the runtime must carry its captured projection to publication")
        return method(frame or self.frame)

    def event(self, decision, snapshot, frame=None, now=STAMP, projection=None):
        frame = frame or self.frame
        event = {"targets": [{"detection_id": 1, "stable_id": 1, "depth_valid": True, "blockers": []}]}
        bridge.attach_depth_evidence(event, decision, frame, self.config,
            projection or self.projection, snapshot=snapshot, now_ns=now)
        return event

    def test_same_frame_keeps_original_transform_after_new_valid_feedback(self):
        decision = self.runtime.process_frame(self.frame)
        self.assertTrue(self.projection.update(self.message(STAMP + 10_000_000, x=0.1325), STAMP + 10_000_000))
        take = getattr(self.runtime, "take_projection_snapshot", None)
        if callable(take):
            event = self.event(decision, take(self.frame), now=STAMP + 10_000_000)
        else:
            # Exercise the original double-read bug, rather than fail on a missing API.
            event = {"targets": [{"detection_id": 1, "stable_id": 1, "depth_valid": True, "blockers": []}]}
            bridge.attach_depth_evidence(event, decision, self.frame, self.config, self.projection)
        np.testing.assert_allclose(event["targets"][0]["base_xyz_m"], [0.1275, 0, 0.57605], atol=1e-7)
        np.testing.assert_allclose(event["frame_projection"]["T_base_camera"], self.runtime.pipeline.transform)
        self.assertFalse(event["frame_projection"]["physically_validated"])

    def test_missing_snapshot_does_not_fall_back_to_new_feedback(self):
        decision = self.runtime.process_frame(self.frame)
        self.snapshot()
        event = self.event(decision, None)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "frame_projection_missing")

    def test_other_frame_cannot_consume_or_reuse_the_snapshot(self):
        decision = self.runtime.process_frame(self.frame)
        other = self.new_frame(sequence=2, stamp=STAMP + 1)
        self.assertIsNone(self.snapshot(other))
        snapshot = self.snapshot()
        self.assertIsNotNone(snapshot)
        self.assertIsNone(self.snapshot())
        event = self.event(decision, snapshot, frame=other)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])

    def test_invalid_feedback_then_recovery_does_not_revive_old_snapshot(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        bad = self.message(); bad["stationary"] = False
        self.assertFalse(self.projection.update(bad, STAMP))
        self.assertTrue(self.projection.update(self.message(), STAMP))
        event = self.event(decision, snapshot)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "frame_projection_invalidated")

    def test_stale_capture_supplies_no_geometry_or_display_transform(self):
        frame = self.new_frame(stamp=STAMP + 250_000_001)
        decision = self.runtime.process_frame(frame)
        snapshot = self.snapshot(frame)
        self.assertIsNone(self.runtime.pipeline.transform)
        event = self.event(decision, snapshot, frame=frame, now=STAMP + 250_000_001)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "robot_state_stale")

    def test_publication_rejects_stale_current_feedback(self):
        decision = self.runtime.process_frame(self.frame)
        event = self.event(decision, self.snapshot(), now=STAMP + 250_000_001)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "robot_state_stale")

    def test_foreign_projector_cannot_replay_a_snapshot(self):
        decision = self.runtime.process_frame(self.frame)
        other = self.new_projection(); self.assertTrue(other.update(self.message(), STAMP))
        event = self.event(decision, self.snapshot(), projection=other)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "frame_projection_owner_mismatch")

    def test_geometry_receives_a_copy_not_the_frozen_matrix(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        self.runtime.pipeline.transform[0, 3] = 9
        event = self.event(decision, snapshot)
        np.testing.assert_allclose(event["targets"][0]["base_xyz_m"], [0.1275, 0, 0.57605], atol=1e-7)
        with self.assertRaises((TypeError, ValueError)):
            snapshot.matrix_4x4[0][3] = 9

    def test_same_timestamp_does_not_authorize_another_frame(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        other = self.new_frame(sequence=2)
        event = self.event(decision, snapshot, frame=other)
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "frame_projection_frame_mismatch")

    def test_malformed_snapshot_is_rejected_instead_of_crashing(self):
        decision = self.runtime.process_frame(self.frame)
        self.snapshot()
        event = self.event(decision, {"status": "ready"})
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertEqual(event["targets"][0]["base_pose_status"], "frame_projection_owner_mismatch")

    def test_failed_inference_leaves_no_consumable_snapshot(self):
        class FailedGeometry:
            def process(self, *_args, **_kwargs):
                raise RuntimeError("inference_failed")
        self.runtime.pipeline = FailedGeometry()
        with self.assertRaisesRegex(RuntimeError, "inference_failed"):
            self.runtime.process_frame(self.frame)
        self.assertIsNone(self.snapshot())

    def test_invalidation_between_evidence_and_publication_clears_coordinates(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        event = self.event(decision, snapshot)
        bad = self.message(); bad["stationary"] = False
        self.assertFalse(self.projection.update(bad, STAMP))
        publish = getattr(bridge, "publish_detection_event", None)
        self.assertTrue(callable(publish), "publication must revalidate under the feedback lock")
        output = []
        writer = SimpleNamespace(write=lambda value: output.append(json.loads(json.dumps(value))))
        publish(writer, event, self.frame, self.projection, snapshot, clock=lambda: STAMP)
        self.assertIsNone(output[0]["targets"][0]["base_xyz_m"])
        self.assertEqual(output[0]["frame_projection"]["status"], "frame_projection_invalidated")

    def test_publication_and_invalidation_are_serialized(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        event = self.event(decision, snapshot)
        publish = getattr(bridge, "publish_detection_event", None)
        self.assertTrue(callable(publish), "publication must revalidate under the feedback lock")
        attempt = threading.Event(); done = threading.Event(); output = []
        bad = self.message(); bad["stationary"] = False
        def invalidate():
            attempt.set()
            self.projection.update(bad, STAMP)
            done.set()
        def write(value):
            worker = threading.Thread(target=invalidate, daemon=True)
            worker.start()
            self.assertTrue(attempt.wait(1))
            self.assertFalse(done.wait(0.02), "feedback invalidated while ready evidence was being written")
            output.append(json.loads(json.dumps(value)))
        publish(SimpleNamespace(write=write), event, self.frame, self.projection, snapshot, clock=lambda: STAMP)
        self.assertTrue(done.wait(1))
        self.assertEqual(output[0]["frame_projection"]["status"], "ready")
        self.assertIsNone(self.projection.for_frame(STAMP))

    def test_camera_only_mode_keeps_depth_without_base_coordinates(self):
        self.runtime.projection = None
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        event = {"targets": [{"detection_id": 1, "stable_id": 1, "depth_valid": True, "blockers": []}]}
        bridge.attach_depth_evidence(event, decision, self.frame, self.config)
        self.assertTrue(event["targets"][0]["depth_valid"])
        self.assertIsNotNone(event["targets"][0]["camera_xyz_m"])
        self.assertIsNone(event["targets"][0]["base_xyz_m"])
        self.assertIsNone(snapshot)

    def test_missing_snapshot_reason_survives_publication(self):
        decision = self.runtime.process_frame(self.frame)
        self.snapshot()
        event = self.event(decision, None)
        output = []
        bridge.publish_detection_event(SimpleNamespace(write=lambda value: output.append(value)),
            event, self.frame, self.projection, None, clock=lambda: STAMP)
        self.assertEqual(output[0]["frame_projection"]["status"], "frame_projection_missing")

    def test_invalid_publication_removes_top_level_pose_and_ready_evidence(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        event = self.event(decision, snapshot)
        # build_detection_event serializes these fields from geometry independently
        # of attach_depth_evidence's per-target displayed base coordinates.
        event.update({"status": "ready", "reasons": [], "evidence_id": "sha256:" + "c" * 64,
            "pose": {"frame": "robot_base", "point_m": [0.1275, 0, 0.57605],
                     "axis": [0, 0, 1], "approach": [0, 0, -1], "width_m": 0.04}})
        bad = self.message(); bad["stationary"] = False
        self.assertFalse(self.projection.update(bad, STAMP))
        output = []
        bridge.publish_detection_event(SimpleNamespace(write=lambda value: output.append(value)),
            event, self.frame, self.projection, snapshot, clock=lambda: STAMP)
        self.assertIsNone(output[0]["pose"])
        self.assertIsNone(output[0]["evidence_id"])
        self.assertEqual(output[0]["status"], "uncertain")
        self.assertIn("frame_projection_invalidated", output[0]["reasons"])
        self.assertIsNone(output[0]["targets"][0]["base_xyz_m"])

    def test_stale_publication_cannot_leave_ready_geometry(self):
        decision = self.runtime.process_frame(self.frame)
        snapshot = self.snapshot()
        event = self.event(decision, snapshot)
        event.update({"status": "ready", "reasons": [], "evidence_id": "old",
                      "pose": {"frame": "robot_base", "point_m": [0.1275, 0, 0.57605]}})
        output = []
        bridge.publish_detection_event(SimpleNamespace(write=lambda value: output.append(value)),
            event, self.frame, self.projection, snapshot, clock=lambda: STAMP + 250_000_001)
        self.assertIsNone(output[0]["pose"])
        self.assertIsNone(output[0]["evidence_id"])
        self.assertEqual(output[0]["status"], "uncertain")
        self.assertIn("robot_state_stale", output[0]["reasons"])


if __name__ == "__main__":
    unittest.main()
