import asyncio
from io import BytesIO
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.person_follow.runtime import TrackerWorker
from dummy.tracker import Target
from dummy.vision_service_tracker import MjpegReader, VisionServiceTracker
from dummy.workspace_guard import WorkspaceGuard, _LinkMesh, _read_stl_vertices


def test_2d_follow_never_requests_depth_and_duplicate_is_not_fresh(monkeypatch):
    cfg = {"vision_service": {"mediapipe_face_enabled": False, "yolo_person_enabled": False,
                              "person_lock_enabled": False, "rgbd_enabled": False}}
    tracker = VisionServiceTracker(cfg)
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    received_at = time.time() - 0.1
    tracker.reader.latest_packet = lambda: (frame, None, 1, received_at)
    monkeypatch.setattr(tracker, "detect", lambda _frame: Target(True, kind="face", ts=time.time()))
    def forbidden(_target):
        raise AssertionError("2D control must not make a depth request")
    monkeypatch.setattr(tracker, "_merge_rgbd_target", forbidden)
    first, _, _ = tracker.read_frame()
    second, _, _ = tracker.read_frame()
    assert first.ts == received_at
    assert first.found and not second.found
    tracker.close()


def test_mjpeg_discards_backlog_and_owned_thread_stops(monkeypatch):
    def jpeg(color):
        buf = BytesIO()
        Image.new("RGB", (8, 8), color).save(buf, format="JPEG")
        return buf.getvalue()
    class Response:
        def __init__(self):
            self.sent = False
            self.closed = threading.Event()
        def read(self, _n):
            if not self.sent:
                self.sent = True
                return jpeg("red") + jpeg("blue")
            self.closed.wait(1)
            return b""
        def close(self):
            self.closed.set()
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            self.close()
    response = Response()
    monkeypatch.setattr("dummy.vision_service_tracker.urllib.request.urlopen", lambda *_args, **_kwargs: response)
    reader = MjpegReader("http://test.invalid/raw")
    reader.start()
    try:
        deadline = time.monotonic() + 2
        while reader.sequence == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        frame, _, _, _ = reader.latest_packet()
        assert frame is not None and frame[0, 0, 0] > frame[0, 0, 2]  # newest, blue BGR
    finally:
        reader.close()
    assert reader.thread is None and response.closed.is_set()


def test_detection_worker_joins_before_detector_close():
    class Tracker:
        def __init__(self):
            self.active = False
            self.closed = False
        def open(self):
            return True
        def read(self):
            self.active = True
            time.sleep(0.02)
            self.active = False
            return Target(False)
        def close(self):
            assert not self.active
            self.closed = True
    tracker = Tracker()
    worker = TrackerWorker(tracker, lambda _target, **_kwargs: None, 0.01)
    worker.start()
    worker.close()
    assert tracker.closed and not worker.thread.is_alive()


def test_guard_optimized_z_is_exact_and_cache_preserves_rejection(monkeypatch):
    guard = WorkspaceGuard({"workspace_guard": {"enabled": False}})
    rng = np.random.default_rng(123)
    points = rng.normal(size=(1000, 3))
    transform = np.eye(4)
    transform[:3, :3] = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    transform[2, 3] = 0.2
    guard._links = {"link1": _LinkMesh(points)}
    monkeypatch.setattr(guard, "_link_transforms", lambda _q: {"link1": transform})
    expected = float(np.min((transform @ np.c_[points, np.ones(len(points))].T).T[:, 2]))
    assert guard.min_geometry_z_m([0] * 6) == pytest.approx(expected, abs=1e-12)
    guard.enabled = guard.available = True
    guard.base_bottom_z_m = 0.0
    calls = []
    monkeypatch.setattr(guard, "min_geometry_z_m", lambda q: calls.append(q) or -0.1)
    assert guard.check([0] * 6)[0] is False
    assert guard.check([0] * 6)[0] is False
    assert len(calls) == 1
    assert guard.check([float("nan")] + [0] * 5)[0] is False
    assert len(calls) == 1


def test_ascii_stl_parser(tmp_path):
    path = tmp_path / "test.stl"
    path.write_text("solid test\n vertex 1 2 3\n vertex 4 5 6\nendsolid\n", encoding="ascii")
    assert _read_stl_vertices(path).tolist() == [[1, 2, 3], [4, 5, 6]]
