from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import time


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "services/vision/python/camera_bridge.py"


def load_module():
    assert MODULE.is_file(), "Vision camera bridge is missing"
    spec = importlib.util.spec_from_file_location("vision_camera_bridge", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_worker_keeps_publishing_after_model_load_failure() -> None:
    module = load_module()

    def frames():
        yield SimpleNamespace(sequence=1)
        time.sleep(0.05)
        yield SimpleNamespace(sequence=2)

    def raising_model_factory():
        raise RuntimeError("checkpoint missing")

    runtime = module.CameraRuntime(
        frames(),
        model_factory=raising_model_factory,
    )
    runtime.start()
    try:
        assert runtime.next_raw_frame(timeout=1).sequence >= 1
        deadline = time.monotonic() + 1
        while runtime.status()["inference"]["status"] != "error":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert "checkpoint missing" in runtime.status()["inference"]["error"]
        assert runtime.status()["camera"]["status"] == "ready"
    finally:
        runtime.close()


def test_overlay_uses_tracker_identity_instead_of_frame_order() -> None:
    import numpy as np

    module = load_module()
    image = np.zeros((40, 80, 3), dtype=np.uint8)
    candidates = [
        SimpleNamespace(
            detection_id=4,
            bbox_xyxy=(5, 5, 25, 30),
            prompt_label="bottle",
            score=0.9,
            mask=None,
        ),
        SimpleNamespace(
            detection_id=1,
            bbox_xyxy=(45, 5, 70, 30),
            prompt_label="bottle",
            score=0.8,
            mask=None,
        ),
    ]

    _overlay, targets = module.render_detection_overlay(
        image,
        candidates,
        selected_id=2,
    )

    assert [target["stableId"] for target in targets] == [5, 2]
    assert [target["selected"] for target in targets] == [False, True]


def test_vision_service_source_has_no_robot_control_dependency() -> None:
    service_root = ROOT / "services/vision"
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in service_root.rglob("*")
        if path.is_file() and path.suffix in {".js", ".py"}
    ).lower()
    for forbidden in (
        "startouch",
        "can" + "0",
        "move_joint",
        "software_stop",
    ):
        assert forbidden not in source
