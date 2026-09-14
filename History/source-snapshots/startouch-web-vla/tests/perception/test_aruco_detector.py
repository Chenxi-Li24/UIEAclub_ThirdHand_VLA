import numpy as np

from uiea_thirdhand_vla.perception.detectors.aruco_detector import ArucoDetector


def test_detect_normalizes_scalar_marker_ids(monkeypatch) -> None:
    """OpenCV scalar IDs must produce the same public detection as (N, 1) IDs."""
    corner = np.array(
        [[[10.0, 10.0], [20.0, 10.0], [20.0, 20.0], [10.0, 20.0]]],
        dtype=np.float32,
    )

    class StubArucoDetector:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def detectMarkers(self, _gray):  # noqa: N802 - mirrors OpenCV's API
            return [corner], np.array([17], dtype=np.int32), []

    monkeypatch.setattr("cv2.aruco.ArucoDetector", StubArucoDetector)
    detector = ArucoDetector()
    detector.K = None

    detections = detector.detect(np.zeros((32, 32, 3), dtype=np.uint8))

    assert len(detections) == 1
    assert detections[0].id == 17
    assert detections[0].label == "aruco_17"
