"""Recompute held-out dual-camera metrics from immutable retained images."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from vision.geometry import validate_transform

from vision_models.calibration_capture import CalibrationCaptureError
from vision_models.calibration_targets import (
    AprilGridSpec,
    CharucoSpec,
    detect_target_corners,
)
from vision_models.dual_camera_candidate import DualCameraCandidate
from vision_models.legacy_dual_camera_validation import (
    evaluate_legacy_candidate_pair,
    summarize_legacy_candidate,
)

MAX_VALIDATION_BYTES = 16 * 1024 * 1024
LUMOS_EDGE_NORMALIZED_RADIUS = 0.45


def _canonical(payload: Any) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError(
            "relative validation must be finite JSON"
        ) from exc


def _content_id(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


def _valid_content_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@dataclass(frozen=True)
class RelativeValidationEvidence:
    """Typed metrics independently recomputed from ten held-out camera pairs."""

    validation_id: str
    candidate_id: str
    samples: int
    edge_points: int
    d435_reprojection_rmse_px: float
    lumos_reprojection_rmse_px: float
    lumos_median_px: float
    lumos_p95_px: float
    lumos_edge_p95_px: float
    relative_position_rmse_m: float

    def __post_init__(self) -> None:
        metrics = np.asarray(
            [
                self.d435_reprojection_rmse_px,
                self.lumos_reprojection_rmse_px,
                self.lumos_median_px,
                self.lumos_p95_px,
                self.lumos_edge_p95_px,
                self.relative_position_rmse_m,
            ],
            dtype=float,
        )
        if (
            not _valid_content_id(self.validation_id)
            or not _valid_content_id(self.candidate_id)
            or isinstance(self.samples, bool)
            or not isinstance(self.samples, int)
            or self.samples < 10
            or isinstance(self.edge_points, bool)
            or not isinstance(self.edge_points, int)
            or self.edge_points < 24
            or not np.isfinite(metrics).all()
            or np.any(metrics < 0.0)
            or self.d435_reprojection_rmse_px > 1.5
            or self.lumos_reprojection_rmse_px > 1.0
            or self.lumos_median_px > 1.0
            or self.lumos_p95_px > 2.5
            or self.lumos_edge_p95_px > 4.0
            or self.relative_position_rmse_m > 0.008
        ):
            raise CalibrationCaptureError(
                "relative validation or radial-edge evidence is invalid"
            )
        for name in (
            "d435_reprojection_rmse_px",
            "lumos_reprojection_rmse_px",
            "lumos_median_px",
            "lumos_p95_px",
            "lumos_edge_p95_px",
            "relative_position_rmse_m",
        ):
            object.__setattr__(self, name, float(getattr(self, name)))


def _target(value: Any) -> AprilGridSpec | CharucoSpec:
    if not isinstance(value, dict):
        raise CalibrationCaptureError("relative validation target is invalid")
    try:
        if value.get("family") == "charuco" and set(value) == {
            "family",
            "rows",
            "columns",
            "square_size_m",
            "marker_size_m",
            "dictionary",
        }:
            return CharucoSpec(
                rows=value["rows"],
                columns=value["columns"],
                square_size_m=value["square_size_m"],
                marker_size_m=value["marker_size_m"],
                dictionary=value["dictionary"],
            )
        if value.get("family") == "tag36h11" and set(value) == {
            "family",
            "rows",
            "columns",
            "tag_size_m",
            "spacing_ratio",
        }:
            return AprilGridSpec(
                rows=value["rows"],
                columns=value["columns"],
                tag_size_m=value["tag_size_m"],
                spacing_ratio=value["spacing_ratio"],
            )
    except (TypeError, ValueError) as exc:
        raise CalibrationCaptureError("relative validation target is invalid") from exc
    raise CalibrationCaptureError("relative validation target is invalid")


def _image(root: Path, item: dict[str, Any], prefix: str) -> Path:
    relative = item.get(f"{prefix}_image")
    digest = item.get(f"{prefix}_image_sha256")
    if (
        not isinstance(relative, str)
        or Path(relative).is_absolute()
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        raise CalibrationCaptureError("relative validation image provenance is invalid")
    path = root / relative
    if path.is_symlink():
        raise CalibrationCaptureError("relative validation image cannot be a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file() or resolved.stat().st_size > 8 * 1024 * 1024:
            raise CalibrationCaptureError("relative validation image is unsafe")
        raw = resolved.read_bytes()
    except CalibrationCaptureError:
        raise
    except (OSError, ValueError) as exc:
        raise CalibrationCaptureError(
            "relative validation image provenance is invalid"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != digest:
        raise CalibrationCaptureError("relative validation image integrity check failed")
    return resolved


def _decode(path: Path, *, width: int, height: int, label: str) -> np.ndarray:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CalibrationCaptureError(f"{label} image cannot be read") from exc
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or image.shape != (height, width):
        raise CalibrationCaptureError(f"{label} image dimensions are invalid")
    return image


def _transform(parameters: np.ndarray) -> np.ndarray:
    values = np.asarray(parameters, dtype=float)
    result = np.eye(4, dtype=float)
    result[:3, :3] = Rotation.from_rotvec(values[:3]).as_matrix()
    result[:3, 3] = values[3:]
    return validate_transform(result)


def _independent_lumos_pose(
    candidate: DualCameraCandidate,
    detection,
    initial: np.ndarray,
) -> np.ndarray:
    seed = np.concatenate(
        (Rotation.from_matrix(initial[:3, :3]).as_rotvec(), initial[:3, 3])
    )

    def residual(parameters: np.ndarray) -> np.ndarray:
        pose = _transform(parameters)
        points = detection.object_points @ pose[:3, :3].T + pose[:3, 3]
        pixels, valid = candidate.lumos.project(points)
        errors = pixels - detection.image_points
        if not valid.all():
            errors = np.asarray(errors, dtype=float)
            errors[~valid] = 1000.0
        return errors.reshape(-1)

    solved = least_squares(
        residual,
        seed,
        method="trf",
        loss="soft_l1",
        f_scale=2.0,
        x_scale="jac",
        max_nfev=500,
    )
    if not solved.success or not np.isfinite(solved.x).all():
        raise CalibrationCaptureError("independent Lumos target pose did not converge")
    return _transform(solved.x)


def _close(first: Any, second: Any, *, atol: float = 1e-7) -> bool:
    try:
        return bool(np.allclose(first, second, rtol=0.0, atol=atol))
    except (TypeError, ValueError):
        return False


def _recompute_relative_validation(
    payload: dict[str, Any],
    root: Path,
    candidate: DualCameraCandidate,
) -> RelativeValidationEvidence:
    target = _target(payload["target"])
    results = []
    all_errors: list[np.ndarray] = []
    edge_errors: list[np.ndarray] = []
    position_deltas = []
    metric_keys = {
        "common_points",
        "d435_reprojection_rmse_px",
        "lumos_reprojection_median_px",
        "lumos_reprojection_p95_px",
        "passes_pixel_gate",
        "lumos_errors_px",
        "T_d435_from_board",
    }
    item_keys = {
        "sample_id",
        "lumos_image",
        "lumos_image_sha256",
        "d435_image",
        "d435_image_sha256",
        "capture_skew_ms",
        "metrics",
    }
    for index, item in enumerate(payload["observations"]):
        if not isinstance(item, dict) or set(item) != item_keys:
            raise CalibrationCaptureError("relative validation observation keys are invalid")
        skew = item["capture_skew_ms"]
        if (
            isinstance(skew, bool)
            or not isinstance(skew, (int, float))
            or not math.isfinite(float(skew))
            or not 0.0 <= float(skew) <= 250.0
        ):
            raise CalibrationCaptureError("relative validation capture skew is invalid")
        metrics = item["metrics"]
        if not isinstance(metrics, dict) or set(metrics) != metric_keys:
            raise CalibrationCaptureError("relative validation metrics are invalid")
        lumos_detection = detect_target_corners(
            _decode(
                _image(root, item, "lumos"),
                width=candidate.lumos.width,
                height=candidate.lumos.height,
                label="Lumos",
            ),
            target,
        )
        d435_detection = detect_target_corners(
            _decode(
                _image(root, item, "d435"),
                width=candidate.d435.width,
                height=candidate.d435.height,
                label="D435",
            ),
            target,
        )
        result = evaluate_legacy_candidate_pair(
            d435=candidate.d435,
            lumos=candidate.lumos,
            t_lumos_from_d435=candidate.t_lumos_from_d435,
            d435_detection=d435_detection,
            lumos_detection=lumos_detection,
        )
        if (
            metrics["common_points"] != result.common_points
            or metrics["passes_pixel_gate"] is not result.passes_pixel_gate
            or not _close(
                metrics["d435_reprojection_rmse_px"],
                result.d435_reprojection_rmse_px,
            )
            or not _close(
                metrics["lumos_reprojection_median_px"],
                result.lumos_reprojection_median_px,
            )
            or not _close(
                metrics["lumos_reprojection_p95_px"],
                result.lumos_reprojection_p95_px,
            )
            or not _close(metrics["lumos_errors_px"], result.lumos_errors_px)
            or not _close(metrics["T_d435_from_board"], result.t_d435_from_board)
        ):
            raise CalibrationCaptureError(
                f"relative validation observation {index} metrics changed"
            )
        d435_ids = set(d435_detection.point_ids)
        lumos_index = dict(
            zip(
                lumos_detection.point_ids,
                lumos_detection.image_points,
                strict=True,
            )
        )
        common = tuple(sorted(d435_ids.intersection(lumos_index)))
        common_pixels = np.asarray([lumos_index[identifier] for identifier in common])
        normalized_radius = np.sqrt(
            ((common_pixels[:, 0] - candidate.lumos.cx) / candidate.lumos.fx) ** 2
            + ((common_pixels[:, 1] - candidate.lumos.cy) / candidate.lumos.fy) ** 2
        )
        radial_errors = result.lumos_errors_px[
            normalized_radius >= LUMOS_EDGE_NORMALIZED_RADIUS
        ]
        if len(radial_errors):
            edge_errors.append(radial_errors)
        predicted = candidate.t_lumos_from_d435 @ result.t_d435_from_board
        measured = _independent_lumos_pose(candidate, lumos_detection, predicted)
        position_deltas.append(
            float(np.linalg.norm(measured[:3, 3] - predicted[:3, 3]))
        )
        results.append(result)
        all_errors.append(result.lumos_errors_px)
    expected_summary = summarize_legacy_candidate(
        results,
        candidate_id=candidate.candidate_id,
    )
    if _canonical(expected_summary) != _canonical(payload["summary"]):
        raise CalibrationCaptureError("relative validation summary changed")
    combined = np.concatenate(all_errors)
    radial = np.concatenate(edge_errors) if edge_errors else np.empty(0)
    d435_rmse = math.sqrt(
        np.mean([item.d435_reprojection_rmse_px**2 for item in results])
    )
    return RelativeValidationEvidence(
        validation_id=payload["content_id"],
        candidate_id=candidate.candidate_id,
        samples=len(results),
        edge_points=len(radial),
        d435_reprojection_rmse_px=float(d435_rmse),
        lumos_reprojection_rmse_px=float(math.sqrt(np.mean(combined * combined))),
        lumos_median_px=float(np.median(combined)),
        lumos_p95_px=float(np.percentile(combined, 95)),
        lumos_edge_p95_px=float(np.percentile(radial, 95)) if len(radial) else math.inf,
        relative_position_rmse_m=float(
            math.sqrt(np.mean(np.square(position_deltas)))
        ),
    )


def load_relative_validation_evidence(
    path: Path | str,
    candidate: DualCameraCandidate,
) -> RelativeValidationEvidence:
    """Verify images and recompute every metric required by the runtime foundation."""

    if not isinstance(candidate, DualCameraCandidate):
        raise CalibrationCaptureError("typed dual-camera candidate is required")
    source = Path(path)
    if source.is_symlink():
        raise CalibrationCaptureError("relative validation cannot be a symlink")
    try:
        source = source.resolve(strict=True)
        if not source.is_file() or source.stat().st_size > MAX_VALIDATION_BYTES:
            raise CalibrationCaptureError("relative validation is unsafe")
        payload = json.loads(source.read_text(encoding="utf-8"))
    except CalibrationCaptureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CalibrationCaptureError("relative validation cannot be parsed") from exc
    expected_keys = {
        "schema_version",
        "candidate_id",
        "target",
        "motion_or_robot_access",
        "observations",
        "summary",
        "content_id",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise CalibrationCaptureError("relative validation keys are invalid")
    unsigned = dict(payload)
    supplied_id = unsigned.pop("content_id")
    summary = payload["summary"]
    observations = payload["observations"]
    if (
        supplied_id != _content_id(unsigned)
        or payload["schema_version"] != 1
        or payload["candidate_id"] != candidate.candidate_id
        or payload["motion_or_robot_access"] is not False
        or not isinstance(summary, dict)
        or not isinstance(observations, list)
        or len(observations) != 10
        or summary.get("candidate_id") != candidate.candidate_id
        or summary.get("samples") != 10
        or summary.get("relative_extrinsic_validated") is not True
        or summary.get("executable") is not False
    ):
        raise CalibrationCaptureError("relative validation integrity check failed")
    summary_unsigned = dict(summary)
    summary_id = summary_unsigned.pop("content_id", None)
    if summary_id != _content_id(summary_unsigned):
        raise CalibrationCaptureError("relative validation summary integrity check failed")
    root = source.parent.resolve()
    sample_ids = []
    for item in observations:
        if not isinstance(item, dict):
            raise CalibrationCaptureError("relative validation observation is invalid")
        sample_ids.append(item.get("sample_id"))
        _image(root, item, "lumos")
        _image(root, item, "d435")
    if any(not isinstance(value, str) or not value for value in sample_ids) or len(
        set(sample_ids)
    ) != len(sample_ids):
        raise CalibrationCaptureError("relative validation sample IDs are invalid")
    result = _recompute_relative_validation(payload, root, candidate)
    if result.validation_id != supplied_id or result.candidate_id != candidate.candidate_id:
        raise CalibrationCaptureError("relative validation recomputation changed sources")
    return result


__all__ = ["RelativeValidationEvidence", "load_relative_validation_evidence"]
