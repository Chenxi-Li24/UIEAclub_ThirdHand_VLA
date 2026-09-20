import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dummy.config import load_config
from dummy.director import DummyDirector
from dummy.filters import OneEuro
from dummy.follow_director import FollowDirector
from dummy.gestures import GestureLibrary
from dummy.mediapipe_face import target_from_mediapipe_detection, target_from_mediapipe_result
from dummy.motion_player import MotionPlayer
from dummy.motion_gate import require_motion_enable
from dummy.robot_ws_client import RobotSnapshot
from dummy.state_machine import State
from dummy.touch_r1_adapter import TouchR1Adapter
from dummy.tracker import Target
from dummy.vision_service_tracker import VisionServiceTracker


class Snapshot:
    def __init__(self):
        self.joints_deg = [0, 0, 0, 0, 0, 0]


class FakeAdapter:
    def __init__(self):
        self.snapshot = Snapshot()
        self.sent = []
        self.grip = []

    async def get_state(self):
        return self.snapshot

    async def send_joint_target(self, joints):
        self.snapshot.joints_deg = list(joints)
        self.sent.append(list(joints))

    async def set_gripper(self, position):
        self.grip.append(position)


class FakeBoundingBox:
    origin_x = 100
    origin_y = 80
    width = 120
    height = 100


class FakeCategory:
    score = 0.91


class FakeDetection:
    bounding_box = FakeBoundingBox()
    categories = [FakeCategory()]


class FakeLowScoreCategory:
    score = 0.20


class FakeLowScoreDetection:
    bounding_box = FakeBoundingBox()
    categories = [FakeLowScoreCategory()]


class FakeMediaPipeResult:
    detections = [FakeLowScoreDetection(), FakeDetection()]


class FarHighScoreBox:
    origin_x = 420
    origin_y = 260
    width = 100
    height = 100


class FarHighScoreCategory:
    score = 0.95


class FarHighScoreDetection:
    bounding_box = FarHighScoreBox()
    categories = [FarHighScoreCategory()]


class NearLowerScoreBox:
    origin_x = 80
    origin_y = 20
    width = 140
    height = 140


class NearLowerScoreCategory:
    score = 0.70


class NearLowerScoreDetection:
    bounding_box = NearLowerScoreBox()
    categories = [NearLowerScoreCategory()]


class TwoFaceResult:
    detections = [FarHighScoreDetection(), NearLowerScoreDetection()]


def test_real_follow_requires_explicit_motion_enable():
    try:
        require_motion_enable(False)
    except RuntimeError as exc:
        assert "--enable-motion" in str(exc)
    else:
        raise AssertionError("real follow accepted an unarmed launch")

    require_motion_enable(True)


def test_one_euro_runs():
    filt = OneEuro(10)
    assert len([filt(x) for x in [0, 1, 2, 3]]) == 4


def test_mediapipe_result_prefers_candidate_nearest_existing_lock():
    target, _debug = target_from_mediapipe_result(
        TwoFaceResult(), 640, 480, reference=(150, 90)
    )

    assert target.u == 150
    assert target.v == 90
    assert target.score == 0.70


def test_mediapipe_face_detection_maps_to_center_target():
    target, debug = target_from_mediapipe_detection(FakeDetection(), 640, 480)

    assert target.found
    assert target.kind == "mediapipe_face"
    assert target.u == 160
    assert target.v == 130
    assert target.score == 0.91
    assert debug["bbox"] == (100, 80, 120, 100)


def test_mediapipe_result_selects_highest_score_face():
    target, debug = target_from_mediapipe_result(FakeMediaPipeResult(), 640, 480)

    assert target.found
    assert target.score == 0.91
    assert debug["bbox"] == (100, 80, 120, 100)


def test_gesture_library_contains_required():
    names = set(GestureLibrary(load_config()).names())
    assert {"idle_breathe", "nod", "head_tilt", "droop", "perk_up", "wiggle", "search", "sleep", "wake_up"} <= names


def test_motion_player_fake():
    async def run():
        cfg = load_config()
        fake = FakeAdapter()
        await MotionPlayer(fake, cfg).play("nod", GestureLibrary(cfg).get("nod"))
        assert fake.sent

    asyncio.run(run())


def test_vision_service_tracker_holds_recent_target():
    cfg = load_config()
    tracker = VisionServiceTracker(cfg)
    tracker.target_hold_s = 10.0
    tracker.last_target = Target(True, 123, 234, 640, 480, 0.5, "person_motion", 1e12)

    held = tracker._held_target()

    assert held.found
    assert held.kind == "person_motion_hold"
    assert held.u == 123
    assert held.v == 234


def test_vision_service_tracker_rejects_motion_before_face_lock():
    cfg = load_config()
    cfg.setdefault("vision_service", {})["motion_requires_face_lock"] = True
    tracker = VisionServiceTracker(cfg)

    assert not tracker._motion_allowed(Target(True, 320, 240, 640, 480, 0.5, "person_motion", 1.0))


def test_vision_service_tracker_allows_motion_near_recent_face_lock():
    cfg = load_config()
    cfg.setdefault("vision_service", {})["motion_requires_face_lock"] = True
    tracker = VisionServiceTracker(cfg)
    tracker.last_target = Target(True, 300, 240, 640, 480, 0.5, "face", 1e12)

    assert tracker._motion_allowed(Target(True, 330, 250, 640, 480, 0.5, "person_motion", 1e12))


def test_vision_service_tracker_requires_sustained_center_wave_for_wave_lock():
    cfg = load_config()
    cfg.setdefault("vision_service", {})["motion_requires_face_lock"] = True
    cfg["vision_service"]["wave_lock_enabled"] = True
    cfg["vision_service"]["wave_lock_frames"] = 3
    tracker = VisionServiceTracker(cfg)
    motion = Target(True, 330, 250, 640, 480, 0.04, "person_motion", 1e12)

    assert not tracker._motion_allowed(motion)
    assert not tracker._motion_allowed(motion)
    assert tracker._motion_allowed(motion)
    assert tracker.last_target.kind == "wave_lock"


def test_vision_service_tracker_rejects_far_motion_after_wave_lock():
    cfg = load_config()
    cfg.setdefault("vision_service", {})["motion_requires_face_lock"] = True
    tracker = VisionServiceTracker(cfg)
    tracker.last_target = Target(True, 320, 240, 640, 480, 0.5, "wave_lock", 1e12)

    assert not tracker._motion_allowed(Target(True, 40, 240, 640, 480, 0.5, "person_motion", 1e12))
    assert tracker._motion_allowed(Target(True, 350, 250, 640, 480, 0.5, "person_motion", 1e12))


def test_vision_service_tracker_treats_mediapipe_face_as_lock():
    cfg = load_config()
    tracker = VisionServiceTracker(cfg)
    tracker.last_target = Target(True, 130, 140, 640, 480, 0.25, "mediapipe_face", 1e12)

    assert not tracker._near_existing_lock(440, 140)
    assert tracker._near_existing_lock(150, 145)


def test_vision_service_tracker_releases_stale_image_position_quickly():
    import time

    cfg = load_config()
    tracker = VisionServiceTracker(cfg)
    tracker.last_target = Target(
        True, 130, 140, 640, 480, 0.8, "mediapipe_face", time.time() - 2.0
    )

    assert not tracker._held_target().found


def test_vision_service_tracker_does_not_redetect_the_same_camera_frame():
    import time
    import numpy as np

    class RepeatingReader:
        def __init__(self):
            self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
            self.sequence = 7
            self.received_at = time.time()

        def latest(self):
            return self.frame.copy(), None

        def latest_packet(self):
            return self.frame.copy(), None, self.sequence, self.received_at

    cfg = load_config()
    tracker = VisionServiceTracker(cfg)
    tracker.reader = RepeatingReader()
    calls = []

    def detect(frame):
        calls.append(frame)
        target = Target(True, 200, 180, 640, 480, 0.9, "mediapipe_face", time.time())
        tracker.last_target = target
        return target

    tracker.detect = detect

    first, _frame, _error = tracker.read_frame()
    second, _frame, _error = tracker.read_frame()

    assert first.kind == "mediapipe_face"
    assert second.kind == "mediapipe_face_hold"
    assert len(calls) == 1


def test_vision_service_tracker_rejects_an_expired_camera_frame():
    import time
    import numpy as np

    class StaleReader:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        def latest(self):
            return self.frame.copy(), None

        def latest_packet(self):
            return self.frame.copy(), None, 9, time.time() - 5.0

    cfg = load_config()
    cfg.setdefault("vision_service", {})["max_frame_age_s"] = 0.5
    tracker = VisionServiceTracker(cfg)
    tracker.reader = StaleReader()
    tracker.detect = lambda _frame: Target(
        True, 200, 180, 640, 480, 0.9, "mediapipe_face", time.time()
    )

    target, _frame, _error = tracker.read_frame()

    assert not target.found
    assert target.kind == "vision_frame_stale"


def test_vision_service_tracker_disables_unreliable_upperbody_initial_lock():
    cfg = load_config()
    tracker = VisionServiceTracker(cfg)

    assert tracker.upperbody_lock_enabled is False
    assert tracker.upperbody is None


def test_follow_director_holds_last_target_when_detection_drops():
    cfg = load_config()
    follow = FollowDirector(cfg)
    joints = [0, 0, 0, 0, 0, 0]

    first = follow.target_for(joints, Target(True, 520, 240, 640, 480, 0.5, "person_motion", 1.0))
    held = follow.target_for(first, Target(False, w=640, h=480, ts=1.1))

    assert held[0] == first[0]
    assert held[3] == first[3]
    assert held[5] == first[5]


def test_follow_director_does_not_chase_a_stale_held_pixel_position():
    cfg = load_config()
    follow = FollowDirector(cfg)
    joints = [10, -2, -4, 40, 1, 2]
    follow.reset_base(joints)
    held_target = Target(
        True, 40, 100, 640, 480, 0.2, "mediapipe_face_hold", 1.0
    )

    command = follow.target_for(joints, held_target)

    assert command == joints


def test_follow_director_adds_small_roll_expression():
    cfg = load_config()
    follow = FollowDirector(cfg)
    joints = [0, 0, 0, 0, 0, 0]

    cmd = follow.target_for(joints, Target(True, 520, 240, 640, 480, 0.5, "face", 1.0))

    assert cmd[0] != 0
    assert cmd[3] == 0
    assert cmd[4] == 0
    assert 0 < abs(cmd[5]) <= float(cfg.get("follow", {}).get("max_roll_step_deg", 1.0))


def test_follow_director_incrementally_chases_persistent_vertical_error():
    cfg = load_config()
    follow = FollowDirector(cfg)
    joints = [0, 0, 0, 10, 0, 0]
    target = Target(True, 320, 120, 640, 480, 0.5, "mediapipe_face", 1.0)

    first = follow.target_for(joints, target)
    second = follow.target_for(first, target)

    assert second[3] > first[3]


def test_follow_director_keeps_chasing_after_reaching_previous_desired():
    cfg = load_config()
    follow = FollowDirector(cfg)
    target = Target(True, 320, 120, 640, 480, 0.5, "mediapipe_face", 1.0)
    first = follow.target_for([0, 0, 0, 10, 0, 0], target)
    for _ in range(3):
        first = follow.target_for(first, target)

    next_cmd = follow.target_for(first, target)

    assert next_cmd[3] > first[3]


def test_follow_director_bounds_pan_and_tilt_excursion_from_lock_pose():
    cfg = load_config()
    cfg["follow"]["max_pan_correction_deg"] = 55.0
    cfg["follow"]["max_tilt_correction_deg"] = 30.0
    follow = FollowDirector(cfg)
    base = [0, -2, -4, 33, 1, 2]
    command = list(base)
    target = Target(True, 0, 0, 640, 480, 0.9, "mediapipe_face", 1.0)

    for _ in range(30):
        command = follow.target_for(command, target)

    assert 22.0 < abs(command[0] - base[0]) <= 55.0
    assert 22.0 < abs(command[3] - base[3]) <= 30.0


def test_follow_director_never_commands_beyond_robot_joint_limits():
    cfg = load_config()
    cfg["follow"]["max_pan_correction_deg"] = 55.0
    cfg["follow"]["max_tilt_correction_deg"] = 30.0
    follow = FollowDirector(cfg)
    command = [160, 0, -4, 96, 0, 0]
    target = Target(True, 0, 0, 640, 480, 0.9, "mediapipe_face", 1.0)

    for _ in range(20):
        command = follow.target_for(command, target)

    limits = cfg["robot"]["joint_limits_deg"]
    assert limits[0][0] <= command[0] <= limits[0][1]
    assert limits[3][0] <= command[3] <= limits[3][1]


def test_follow_director_steps_from_measured_joints_not_predicted_commands():
    cfg = load_config()
    follow = FollowDirector(cfg)
    base = [0, -2, -4, 33, 1, 2]
    follow.reset_base(base)
    follow.current = [18, -2, -4, 50, 1, 2]
    measured = [4, -2, -4, 37, 1, 2]
    target = Target(True, 20, 80, 640, 480, 0.9, "mediapipe_face", 1.0)

    command = follow.target_for(measured, target)

    max_step = float(cfg["follow"]["max_step_deg"])
    assert abs(command[0] - measured[0]) <= max_step
    assert abs(command[3] - measured[3]) <= max_step


def test_follow_director_search_target_is_bounded_around_base():
    cfg = load_config()
    follow = FollowDirector(cfg)
    base = [0, 0, 0, 0, 0, 0]
    follow.reset_base(base)

    current = [20, 0, 0, 0, 0, 0]
    targets = []
    for _ in range(5):
        previous = current
        current = follow.search_target(current, phase=1.5708)
        targets.append(current)
        assert abs(current[0] - previous[0]) <= float(cfg["follow"]["max_step_deg"])
    search_max = float(cfg.get("follow", {}).get("search_max_deg", 4.0))

    assert targets[-1][0] <= search_max + 0.1


def test_follow_director_search_scans_pan_and_tilt_around_last_seen_pose():
    import math

    cfg = load_config()
    follow = FollowDirector(cfg)
    last_seen_pose = [20, -2, -4, 35, 1, 2]
    follow.reset_base(last_seen_pose)

    command = follow.search_target(last_seen_pose, phase=math.pi / 2)

    assert command[0] != last_seen_pose[0]
    assert command[3] != last_seen_pose[3]
    assert abs(command[0] - last_seen_pose[0]) <= float(cfg["follow"]["search_max_deg"])
    assert abs(command[3] - last_seen_pose[3]) <= float(cfg["follow"]["search_tilt_max_deg"])


def test_director_starts_search_around_the_last_seen_robot_pose():
    cfg = load_config()
    cfg.setdefault("vision_service", {})["enabled"] = False
    director = DummyDirector(FakeAdapter(), cfg)
    director.follow.reset_base([0, 0, -4, 33, 0, 0])
    last_seen_pose = [18, -2, -4, 41, 1, 2]

    director._enter_search(last_seen_pose, now=123.0)

    assert director.state == State.SEARCH
    assert director.search_started == 123.0
    assert director.follow.base == last_seen_pose


def test_director_recovers_when_a_search_command_hits_a_joint_limit():
    class RejectingAdapter(FakeAdapter):
        async def send_joint_target(self, joints):
            raise ValueError("J4 target outside limit")

    cfg = load_config()
    cfg.setdefault("vision_service", {})["enabled"] = False
    director = DummyDirector(RejectingAdapter(), cfg)
    joints = [18, -2, -4, 95, 1, 2]
    director.follow.reset_base([0, 0, -4, 33, 0, 0])

    sent = asyncio.run(director._send_search_command(joints, phase=1.0))

    assert sent is False
    assert director.follow.base == joints


def test_touch_r1_adapter_sends_timed_move_joint_for_follow_speed():
    class FakeRobotClient:
        def __init__(self):
            self.snapshot = RobotSnapshot(
                connected=True,
                state_ready=True,
                moving=False,
                joints_deg=[0, 0, -4, 33, 0, 0],
                state_name="IDLE",
            )
            self.commands = []

        async def command(self, command, **kwargs):
            self.commands.append((command, kwargs))

        async def refresh_state(self, timeout=2.0):
            del timeout
            return self.snapshot

    async def exercise():
        adapter = TouchR1Adapter(load_config())
        adapter.client = FakeRobotClient()
        await adapter.send_joint_target([4, 0, -4, 37, 0, 0])
        return adapter.client.commands[-1]

    command, kwargs = asyncio.run(exercise())

    assert command == "move_joint"
    assert kwargs["joints_deg"] == [4.0, 0.0, -4.0, 37.0, 0.0, 0.0]
    assert kwargs["time_sec"] == 0.2


def test_touch_r1_adapter_refreshes_joint_state_before_delta_validation():
    class FreshStateClient:
        def __init__(self):
            self.snapshot = RobotSnapshot(
                connected=True,
                state_ready=True,
                moving=False,
                joints_deg=[0, 0, -4, 33, 0, 0],
                state_name="IDLE",
            )
            self.commands = []

        async def refresh_state(self, timeout=2.0):
            del timeout
            self.snapshot.joints_deg = [4, 0, -4, 37, 0, 0]
            return self.snapshot

        async def command(self, command, **kwargs):
            self.commands.append((command, kwargs))

    async def exercise():
        adapter = TouchR1Adapter(load_config())
        adapter.client = FreshStateClient()
        await adapter.send_joint_target([8, 0, -4, 41, 0, 0])
        return adapter.client.commands[-1]

    command, kwargs = asyncio.run(exercise())

    assert command == "move_joint"
    assert kwargs["joints_deg"][0] == 8.0
    assert kwargs["joints_deg"][3] == 41.0


def test_single_instance_lock_rejects_second_follow_controller(tmp_path=None):
    import tempfile
    from dummy.single_instance import SingleInstanceLock

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "follow.lock"
        first = SingleInstanceLock(path)
        second = SingleInstanceLock(path)
        first.acquire()
        try:
            try:
                second.acquire()
            except RuntimeError as exc:
                assert "already running" in str(exc)
            else:
                raise AssertionError("second controller acquired the same lock")
        finally:
            first.release()


def test_prepare_color_frame_preserves_camera_bgr_channels():
    import numpy as np
    from dummy.display import prepare_color_frame

    frame = np.array([[[10, 40, 220], [5, 90, 130]]], dtype=np.uint8)

    prepared = prepare_color_frame(frame, mirror=False)

    assert prepared.tolist() == frame.tolist()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OFFLINE_OK")
