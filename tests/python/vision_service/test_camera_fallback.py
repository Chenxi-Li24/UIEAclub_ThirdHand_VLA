from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import time

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "services/vision/python/camera_bridge.py"


def load_module():
    assert MODULE.is_file(), "Vision camera bridge is missing"
    spec = importlib.util.spec_from_file_location("vision_camera_bridge", MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stream_demand_is_disabled_by_default_and_validates_updates() -> None:
    module = load_module()
    demand = module.StreamDemand()

    assert not demand.requested("raw")
    assert not demand.requested("vision")
    assert not demand.requested("depth")
    demand.set_enabled("depth", True)
    assert demand.requested("depth")
    assert not demand.requested("raw")


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


def test_grounded_sam_import_does_not_require_undeployed_full_pipeline() -> None:
    python_root = ROOT / "services/vision/python"
    runtime_python = ROOT / "local/runtimes/python/bin/python"
    environment = {
        **os.environ,
        "PYTHONPATH": str(python_root),
    }
    completed = subprocess.run(
        [
            str(runtime_python if runtime_python.is_file() else Path(sys.executable)),
            "-c",
            "from thirdhand_va.vision.perception.grounded_sam import GroundedSamBackend",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


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


def selected_snapshot_fixture(*, state="confirmed", depth_supported=True, mask=None):
    if mask is None:
        mask = np.array([[False, True], [True, False]], dtype=bool)
    rgb = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
    depth = np.array([[0.1, 0.2], [0.3, 0.4]], dtype=np.float32)
    xyz = np.dstack((depth, depth + 1, depth + 2)).astype(np.float32)
    candidate = SimpleNamespace(
        detection_id=7,
        label="bottle",
        score=0.91,
        bbox_xyxy=(1.0, 2.0, 3.0, 4.0),
        mask=mask,
    )
    track = SimpleNamespace(
        stable_id=2,
        state=state,
        depth_supported=depth_supported,
        blockers=() if depth_supported else ("depth_invalid",),
        candidate=candidate,
    )
    decision = SimpleNamespace(
        selected_stable_id=2,
        status="ready",
        reasons=(),
        tracks=(track,),
    )
    frame = SimpleNamespace(
        sequence=42,
        monotonic_ns=123456789,
        camera_serial="lumos-test",
        rgb=rgb,
        depth_m=depth,
        xyz_camera_m=xyz,
    )
    return frame, decision


def test_selected_target_snapshot_writes_same_frame_arrays_and_metadata(tmp_path) -> None:
    module = load_module()
    frame, decision = selected_snapshot_fixture()

    result = module.write_selected_target_snapshot(
        frame,
        decision,
        request_id="snapshot-1",
        output_dir=tmp_path,
        observed_at_ms=987654,
    )

    assert result["ok"] is True
    assert result["schema"] == "thirdhand-selected-target-bundle-v1"
    assert result["frame_id"] == 42
    with np.load(result["path"], allow_pickle=False) as bundle:
        np.testing.assert_array_equal(bundle["rgb"], frame.rgb)
        np.testing.assert_array_equal(bundle["depth_m"], frame.depth_m)
        np.testing.assert_array_equal(bundle["xyz_camera_m"], frame.xyz_camera_m)
        np.testing.assert_array_equal(
            bundle["mask"], np.array([[False, True], [True, False]])
        )
        metadata = __import__("json").loads(str(bundle["metadata_json"]))
    assert metadata == {
        "bbox_xyxy": [1.0, 2.0, 3.0, 4.0],
        "blockers": [],
        "camera_serial": "lumos-test",
        "depth_valid": True,
        "frame_id": 42,
        "length_unit": "m",
        "monotonic_ns": 123456789,
        "observed_at_ms": 987654,
        "point_frame": "xvisio_color",
        "request_id": "snapshot-1",
        "schema": "thirdhand-selected-target-bundle-v1",
        "selected_stable_id": 2,
        "status": "ready",
        "track_state": "confirmed",
    }


def test_raw_frame_snapshot_writes_aligned_arrays(tmp_path) -> None:
    module = load_module()
    frame, _ = selected_snapshot_fixture()
    result = module.write_raw_frame_snapshot(
        frame, request_id="raw-1", output_dir=tmp_path, observed_at_ms=987654,
    )
    assert result["ok"] is True
    assert result["schema"] == "thirdhand-raw-rgbd-frame-v1"
    with np.load(result["path"], allow_pickle=False) as bundle:
        np.testing.assert_array_equal(bundle["rgb"], frame.rgb)
        np.testing.assert_array_equal(bundle["depth_m"], frame.depth_m)
        np.testing.assert_array_equal(bundle["xyz_camera_m"], frame.xyz_camera_m)
        metadata = __import__("json").loads(str(bundle["metadata_json"]))
    assert metadata["frame_id"] == 42
    assert metadata["point_frame"] == "xvisio_color"
    assert metadata["length_unit"] == "m"


@pytest.mark.parametrize(
    ("state", "depth_supported", "mask", "code"),
    [
        ("lost", True, None, "selected_target_lost"),
        ("confirmed", False, None, "selected_target_depth_invalid"),
        ("confirmed", True, np.zeros((2, 2), dtype=bool), "selected_target_mask_invalid"),
        ("confirmed", True, np.ones((1, 2), dtype=bool), "selected_target_mask_invalid"),
    ],
)
def test_selected_target_snapshot_rejects_invalid_target_without_file(
    tmp_path, state, depth_supported, mask, code
) -> None:
    module = load_module()
    frame, decision = selected_snapshot_fixture(
        state=state, depth_supported=depth_supported, mask=mask
    )

    result = module.write_selected_target_snapshot(
        frame,
        decision,
        request_id="snapshot-invalid",
        output_dir=tmp_path,
        observed_at_ms=987654,
    )

    assert result == {
        "type": "selected_target_export_result",
        "requestId": "snapshot-invalid",
        "ok": False,
        "code": code,
    }
    assert list(tmp_path.iterdir()) == []
