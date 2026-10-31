import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services/edge-agent/src"))
from thirdhand_edge.telemetry import normalize_robot_state


def test_actual_and_target_are_separate_units_are_explicit_and_unavailable_fields_are_not_zeroes():
    raw = {"type": "robot_state", "ts": 1793350800000, "connected": True, "moving": True,
           "joints_deg": [0, 90, -90, 0, 0, 0], "velocities_deg_s": [1, 2, 3, 0, 0, 0],
           "target_joints_deg": [10, 80, -80, 0, 0, 0], "torques": [0.1] * 6,
           "pose_frame": "robot_flange", "flange_position_m": [0.2, 0, 0.3], "flange_euler_rad": [0, 0, 0]}
    sample = normalize_robot_state(raw, monotonic_ns=123456789, received_at="2026-10-30T09:00:00.100Z")
    assert sample["jointPositionRad"][1] == math.pi / 2
    assert sample["extra"]["target"]["jointPositionRad"][0] == math.radians(10)
    assert sample["extra"]["rawState"] == raw
    assert sample["monotonicNs"] == "123456789"
    assert sample["clockQuality"] == "estimated"
    assert sample["jointCurrentA"] is None and sample["fieldAvailability"]["jointCurrentA"] is False
    assert sample["tcpPositionM"] is None, "a measured flange point must not be labelled as tool TCP"
    assert sample["extra"]["flangePositionM"] == [0.2, 0, 0.3]


def test_missing_capture_time_and_robot_status_are_explicit_unknown_quality_not_fake_measurements():
    sample = normalize_robot_state({"type": "robot_state", "joints_deg": [0, 1]}, monotonic_ns=9, received_at="2026-10-30T09:00:00.100Z")
    assert sample["jointPositionRad"] == [0, math.radians(1)]
    assert "CAPTURE_TIME_ESTIMATED" in sample["qualityFlags"]
    assert "SDK_STATE_UNKNOWN" in sample["qualityFlags"]
    assert sample["fieldAvailability"]["sdkConnected"] is False


def test_valid_runtime_version_names_survive_normalization_and_cannot_alias_later_mutations():
    versions = {"schema": 1, "tool": "tool-a", "calibration": "cal-a", "sdk": "sdk-a", "framePolicy": "flange-v1"}
    sample = normalize_robot_state({"type": "robot_state", "joints_deg": [0] * 6}, versions=versions)
    assert sample["toolVersion"] == "tool-a"
    assert sample["calibrationVersion"] == "cal-a"
    assert sample["extra"]["sourceVersions"] == versions
    versions["sdk"] = "changed"
    assert sample["extra"]["sourceVersions"]["sdk"] == "sdk-a"
