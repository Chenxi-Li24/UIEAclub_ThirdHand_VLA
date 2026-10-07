import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dummy.yunet_face import YuNetFaceDetector


def test_yunet_maps_face_box_and_landmarks_to_frame_coordinates(tmp_path):
    detector = YuNetFaceDetector(tmp_path / "unused.onnx")
    row = [200, 150, 40, 50, 210, 160, 230, 160, 220, 175, 212, 185, 228, 185, .91]
    inputs = []
    detector.detector = SimpleNamespace(setInputSize=inputs.append,
                                       detect=lambda _bgr: (1, np.array([row])))
    faces = detector.detect_all(np.zeros((480, 640, 3), dtype=np.uint8))
    assert inputs == [(640, 480)]
    target, debug = faces[0]
    assert target.kind == "yunet_face" and target.u == 220 and target.v == 175
    assert debug["bbox"] == [200, 150, 40, 50]
    assert len(debug["landmarks"]) == 5
    detector.close()
    assert not detector.available


def test_yunet_rejects_low_score_nonfinite_and_empty_detections(tmp_path):
    detector = YuNetFaceDetector(tmp_path / "unused.onnx")
    low = [20, 10, 40, 50] + [0] * 10 + [.2]
    bad = [float("nan"), 10, 40, 50] + [0] * 10 + [.9]
    detector.detector = SimpleNamespace(setInputSize=lambda _size: None,
                                       detect=lambda _bgr: (2, np.array([low, bad])))
    assert detector.detect_all(np.zeros((48, 64, 3), dtype=np.uint8)) == []
    detector.detector.detect = lambda _bgr: (0, None)
    assert detector.detect_all(np.zeros((48, 64, 3), dtype=np.uint8)) == []


def test_yunet_missing_weights_fail_without_implicit_download(tmp_path):
    detector = YuNetFaceDetector(tmp_path / "missing.onnx")
    with pytest.raises(RuntimeError, match="run prepare_face_model"):
        detector.detect_all(np.zeros((48, 64, 3), dtype=np.uint8))
    assert not detector.available


def test_model_preparation_rejects_corrupt_bytes_before_installation():
    import hashlib
    path = Path(__file__).resolve().parents[1] / "apps/prepare_face_model.py"
    spec = importlib.util.spec_from_file_location("prepare_dummy_face", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = {"size_bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    assert module.verified_payload(b"abc", manifest) == b"abc"
    with pytest.raises(ValueError, match="size mismatch"):
        module.verified_payload(b"ab", manifest)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        module.verified_payload(b"xyz", manifest)
