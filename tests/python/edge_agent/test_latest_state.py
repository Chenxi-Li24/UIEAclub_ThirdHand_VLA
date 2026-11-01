import math
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'services/edge-agent/src'))
from thirdhand_edge.latest_state import make_report
from thirdhand_edge.telemetry import normalize_robot_state


def test_gripper_measurements_are_independent_nullable_and_never_inferred():
    sample = normalize_robot_state({'type': 'robot_state', 'joints_deg': [0] * 6, 'gripper_position': .4})
    assert sample['gripper'] == {'positionRatio': .4, 'widthM': None}
    assert sample['fieldAvailability']['gripperPosition'] is True
    assert sample['fieldAvailability']['gripperWidth'] is False
    for value in [float('nan'), float('inf'), -1, True, 1.1, '1']:
        assert normalize_robot_state({'type': 'robot_state', 'gripper_position': value})['gripper']['positionRatio'] is None


def test_snapshot_age_comes_from_producer_clock_not_http_or_reader_receipt():
    frame = {'type': 'robot_event', 'sequence': 4, 'executorEpoch': 'epoch', 'sourceMode': 'hardware', 'message': {'type': 'robot_state', 'state_sequence': 4, 'producer_monotonic_ns': 1000000000, 'joints_deg': [90] * 6, 'gripper_width_m': .02}}
    report = make_report(frame, {'executorEpoch': 'epoch'}, now_ns=1200000000, wall_ms=1793500000000)
    assert report['sourceAgeMs'] == 200
    assert report['sample']['jointPositionRad'][0] == math.pi / 2
    assert report['sample']['gripper']['widthM'] == .02
    assert report['sample']['extra']['sourceMode'] == 'hardware'
    assert 'rawState' not in report['sample']['extra']
    with pytest.raises(ValueError):
        make_report(frame, {'executorEpoch': 'old'}, now_ns=1200000000)
    with pytest.raises(ValueError):
        make_report(frame, {'executorEpoch': 'epoch'}, now_ns=5000000000)
    with pytest.raises(ValueError):
        make_report(frame, {'executorEpoch': 'epoch'}, now_ns=900000000)


def test_connection_events_do_not_invent_measured_values_or_reuse_state_sequence():
    frame = {'type': 'robot_event', 'sequence': 12, 'executorEpoch': 'epoch',
             'sourceMode': 'hardware', 'sourceMonotonicNs': 1000000000,
             'receivedAt': '2026-11-01T00:00:00Z',
             'message': {'type': 'connection', 'connected': False}}
    report = make_report(frame, {'executorEpoch': 'epoch'}, now_ns=1100000000)
    assert report['sequence'] == 12
    assert report['sample']['sdkConnected'] is False
    assert report['sample']['jointPositionRad'] is None
    assert report['sample']['moving'] is None
    assert report['sample']['gripper'] == {'positionRatio': None, 'widthM': None}
