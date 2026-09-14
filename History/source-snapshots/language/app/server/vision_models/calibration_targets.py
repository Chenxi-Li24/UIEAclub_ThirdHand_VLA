"""Strict calibration-target definitions and target-neutral keyed detections."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml


class CalibrationTargetError(ValueError):
    """Raised when a target definition or detection cannot be trusted."""


@dataclass(frozen=True)
class TargetCorners:
    point_ids: tuple[int, ...]
    object_points: np.ndarray = field(compare=False, repr=False)
    image_points: np.ndarray = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        identifiers = tuple(self.point_ids)
        objects = np.asarray(self.object_points, dtype=np.float64)
        images = np.asarray(self.image_points, dtype=np.float64)
        if (
            len(identifiers) < 4
            or len(set(identifiers)) != len(identifiers)
            or any(
                isinstance(identifier, bool)
                or not isinstance(identifier, int)
                or identifier < 0
                for identifier in identifiers
            )
            or objects.shape != (len(identifiers), 3)
            or images.shape != (len(identifiers), 2)
            or not np.isfinite(objects).all()
            or not np.isfinite(images).all()
        ):
            raise CalibrationTargetError("target corner correspondences are invalid")
        objects.setflags(write=False)
        images.setflags(write=False)
        object.__setattr__(self, "point_ids", identifiers)
        object.__setattr__(self, "object_points", objects)
        object.__setattr__(self, "image_points", images)


@dataclass(frozen=True)
class AprilGridSpec:
    rows: int
    columns: int
    tag_size_m: float
    spacing_ratio: float

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 20
            for value in (self.rows, self.columns)
        ):
            raise CalibrationTargetError("AprilGrid rows and columns must be within [2, 20]")
        dimensions = np.asarray([self.tag_size_m, self.spacing_ratio], dtype=float)
        if (
            not np.isfinite(dimensions).all()
            or not 0.005 <= dimensions[0] <= 0.20
            or not 0.0 <= dimensions[1] <= 1.0
        ):
            raise CalibrationTargetError("AprilGrid metric dimensions are invalid")

    def to_json(self) -> dict[str, float | int | str]:
        return {
            "family": "tag36h11",
            "rows": self.rows,
            "columns": self.columns,
            "tag_size_m": float(self.tag_size_m),
            "spacing_ratio": float(self.spacing_ratio),
        }


@dataclass(frozen=True)
class CharucoSpec:
    rows: int
    columns: int
    square_size_m: float
    marker_size_m: float
    dictionary: str

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or not 3 <= value <= 30
            for value in (self.rows, self.columns)
        ):
            raise CalibrationTargetError("ChArUco rows and columns must be within [3, 30]")
        dimensions = np.asarray([self.square_size_m, self.marker_size_m], dtype=float)
        if (
            not np.isfinite(dimensions).all()
            or not 0.005 <= self.square_size_m <= 0.20
            or not 0.0 < self.marker_size_m < self.square_size_m
        ):
            raise CalibrationTargetError("ChArUco metric dimensions are invalid")
        if self.dictionary != "DICT_5X5_100":
            raise CalibrationTargetError("unsupported ChArUco dictionary")

    def board(self) -> cv2.aruco.CharucoBoard:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
        return cv2.aruco.CharucoBoard(
            (self.columns, self.rows),
            self.square_size_m,
            self.marker_size_m,
            dictionary,
        )

    def to_json(self) -> dict[str, float | int | str]:
        return {
            "family": "charuco",
            "rows": self.rows,
            "columns": self.columns,
            "square_size_m": float(self.square_size_m),
            "marker_size_m": float(self.marker_size_m),
            "dictionary": self.dictionary,
        }


CalibrationTargetSpec = AprilGridSpec | CharucoSpec


def _read_target(path: Path | str) -> dict[str, Any]:
    source = Path(path)
    if source.is_symlink():
        raise CalibrationTargetError("calibration target cannot be a symlink")
    try:
        resolved = source.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > 64 * 1024:
            raise CalibrationTargetError("calibration target file is unsafe")
        payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise CalibrationTargetError("calibration target cannot be parsed") from exc
    if not isinstance(payload, dict):
        raise CalibrationTargetError("calibration target must be a YAML mapping")
    return payload


def load_calibration_target(path: Path | str) -> CalibrationTargetSpec:
    payload = _read_target(path)
    target_type = payload.get("target_type")
    if target_type == "aprilgrid":
        expected = {"target_type", "tagCols", "tagRows", "tagSize", "tagSpacing"}
        if set(payload) != expected:
            raise CalibrationTargetError("AprilGrid target keys are invalid")
        return AprilGridSpec(
            rows=payload["tagRows"],
            columns=payload["tagCols"],
            tag_size_m=payload["tagSize"],
            spacing_ratio=payload["tagSpacing"],
        )
    if target_type == "charuco":
        expected = {
            "target_type",
            "squaresX",
            "squaresY",
            "squareLength",
            "markerLength",
            "dictionary",
        }
        if set(payload) != expected:
            raise CalibrationTargetError("ChArUco target keys are invalid")
        return CharucoSpec(
            rows=payload["squaresY"],
            columns=payload["squaresX"],
            square_size_m=payload["squareLength"],
            marker_size_m=payload["markerLength"],
            dictionary=payload["dictionary"],
        )
    raise CalibrationTargetError("unsupported calibration target type")


def _grayscale(image: np.ndarray) -> np.ndarray:
    frame = np.asarray(image)
    if frame.ndim == 3 and frame.shape[2] == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    elif frame.ndim == 2:
        gray = frame
    else:
        raise CalibrationTargetError("calibration image must be grayscale or BGR")
    if gray.dtype != np.uint8 or min(gray.shape) < 32:
        raise CalibrationTargetError("calibration image must be a non-empty uint8 frame")
    return gray


def _detect_aprilgrid(gray: np.ndarray, spec: AprilGridSpec) -> TargetCorners:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    corners, ids, _rejected = cv2.aruco.ArucoDetector(
        dictionary, parameters
    ).detectMarkers(gray)
    if ids is None:
        raise CalibrationTargetError("AprilGrid was not detected")
    pitch = spec.tag_size_m * (1.0 + spec.spacing_ratio)
    point_ids: list[int] = []
    object_points: list[list[float]] = []
    image_points: list[np.ndarray] = []
    for marker_id, image_corners in zip(ids.reshape(-1), corners, strict=True):
        identifier = int(marker_id)
        if not 0 <= identifier < spec.rows * spec.columns:
            continue
        row, column = divmod(identifier, spec.columns)
        x = column * pitch
        y = row * pitch
        size = spec.tag_size_m
        point_ids.extend(identifier * 4 + index for index in range(4))
        object_points.extend(
            ([x, y, 0.0], [x + size, y, 0.0], [x + size, y + size, 0.0], [x, y + size, 0.0])
        )
        image_points.extend(np.asarray(image_corners, dtype=float).reshape(4, 2))
    if len(point_ids) < 16:
        raise CalibrationTargetError("AprilGrid requires at least four valid tags")
    return TargetCorners(
        point_ids=tuple(point_ids),
        object_points=np.asarray(object_points, dtype=np.float64),
        image_points=np.asarray(image_points, dtype=np.float64),
    )


def _detect_charuco(gray: np.ndarray, spec: CharucoSpec) -> TargetCorners:
    board = spec.board()
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    detector = cv2.aruco.CharucoDetector(board)
    detector.setDetectorParameters(parameters)
    corners, ids, _marker_corners, _marker_ids = detector.detectBoard(gray)
    if ids is None or corners is None or len(ids) < 6:
        raise CalibrationTargetError("ChArUco requires at least six chessboard corners")
    point_ids = tuple(int(value) for value in ids.reshape(-1))
    all_object_points = np.asarray(board.getChessboardCorners(), dtype=np.float64)
    return TargetCorners(
        point_ids=point_ids,
        object_points=all_object_points[np.asarray(point_ids, dtype=int)],
        image_points=np.asarray(corners, dtype=np.float64).reshape(-1, 2),
    )


def detect_target_corners(
    image: np.ndarray,
    target: CalibrationTargetSpec,
) -> TargetCorners:
    gray = _grayscale(image)
    if isinstance(target, AprilGridSpec):
        return _detect_aprilgrid(gray, target)
    if isinstance(target, CharucoSpec):
        return _detect_charuco(gray, target)
    raise CalibrationTargetError("typed calibration target is required")


__all__ = [
    "AprilGridSpec",
    "CalibrationTargetError",
    "CalibrationTargetSpec",
    "CharucoSpec",
    "TargetCorners",
    "detect_target_corners",
    "load_calibration_target",
]
