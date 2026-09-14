#!/usr/bin/env python3
"""Deterministic offline validation for spatial RGB-D bottle selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from thirdhand_va.common.config import VisionConfig
from thirdhand_va.common.contracts import RgbdFrame, VisionDecision
from thirdhand_va.vision.perception.interfaces import RawCandidate
from thirdhand_va.vision.pipeline import VisionPipeline
from thirdhand_va.vision.selection import SelectionRequest, SpatialBottleSelector
from thirdhand_va.vision.visualization import RenderMetrics, encode_jpeg, render_overlay


class SyntheticBackend:
    def __init__(self, candidates: tuple[RawCandidate, ...]) -> None:
        self.candidates = candidates

    def infer(self, rgb: np.ndarray) -> tuple[RawCandidate, ...]:
        return self.candidates


def _mask(center_x: int) -> np.ndarray:
    mask = np.zeros((120, 240), dtype=bool)
    mask[10:35, center_x - 5 : center_x + 5] = True
    mask[35:110, center_x - 15 : center_x + 15] = True
    return mask


def _scene(
    centers: tuple[int, ...],
    *,
    empty_depth_for: int | None = None,
) -> tuple[SyntheticBackend, list[RgbdFrame]]:
    masks = tuple(_mask(center) for center in centers)
    candidates = tuple(
        RawCandidate(
            detection_id=index,
            prompt_label="bottle",
            score=0.92,
            bbox_xyxy=(center - 15, 10, center + 15, 110),
            mask=mask,
            descriptor=None,
        )
        for index, (center, mask) in enumerate(zip(centers, masks), start=1)
    )
    yy, xx = np.indices((120, 240))
    xyz = np.empty((120, 240, 3), dtype=np.float32)
    xyz[..., 0] = (xx - 120.0) * 0.002
    xyz[..., 1] = 0.07
    xyz[..., 2] = 0.45 + (yy - 60.0) * 0.0001
    for index, mask in enumerate(masks, start=1):
        if index == empty_depth_for:
            xyz[mask] = np.nan
            continue
        center = centers[index - 1]
        # Keep synthetic bottle bodies physically separated, matching the
        # generic-bottle task contract and the approach-corridor safety check.
        xyz[..., 0][mask] = (center - 120.0) * 0.002 + (
            xx[mask] - center
        ) * 0.0015
        xyz[..., 1][mask] = (yy[mask] - 60.0) * 0.0015
        xyz[..., 2][mask] = 0.42 + index * 0.02
    frames = [
        RgbdFrame(
            sequence=index,
            monotonic_ns=index * 100_000_000,
            camera_serial="synthetic-offline",
            rgb=np.full((120, 240, 3), 18, dtype=np.uint8),
            depth_m=xyz[..., 2],
            xyz_camera_m=xyz,
        )
        for index in range(1, 8)
    ]
    return SyntheticBackend(candidates), frames


def _run_case(
    config: VisionConfig,
    name: str,
    centers: tuple[int, ...],
    side: str,
    ordinal: int,
    expected_id: int | None,
    *,
    empty_depth_for: int | None = None,
) -> tuple[dict[str, Any], VisionDecision, RgbdFrame]:
    backend, frames = _scene(centers, empty_depth_for=empty_depth_for)
    pipeline = VisionPipeline(config, backend)
    discovery = [
        pipeline.process(frame, now_ns=frame.monotonic_ns + 1_000_000)
        for frame in frames[: config.track_confirmation_hits]
    ][-1]
    eligible = tuple(
        track.candidate
        for track in discovery.tracks
        if track.state == "confirmed" and track.depth_supported
    )
    legacy = SpatialBottleSelector(config.min_horizontal_gap_px).select(
        eligible, SelectionRequest(side, ordinal)
    )
    if legacy.selected is None:
        return (
            {
                "name": name,
                "passed": expected_id is None,
                "status": "rejected",
                "selected_detection_id": None,
                "reasons": list(legacy.reasons),
            },
            discovery,
            frames[config.track_confirmation_hits - 1],
        )
    selected_track = next(
        track
        for track in discovery.tracks
        if track.candidate.detection_id == legacy.selected.detection_id
    )
    if selected_track.stable_id is None or not pipeline.select(
        selected_track.stable_id, f"legacy-validation:{name}"
    ):
        raise RuntimeError("confirmed legacy target could not be reserved")
    results = [
        pipeline.process(frame, now_ns=frame.monotonic_ns + 1_000_000)
        for frame in frames[config.track_confirmation_hits :]
    ]
    result = results[-1]
    actual_id = None if result.target is None else result.target.detection_id
    if expected_id is None:
        passed = result.status == "rejected"
    else:
        passed = result.status == "ready" and actual_id == expected_id
    return (
        {
            "name": name,
            "passed": passed,
            "status": result.status,
            "selected_detection_id": actual_id,
            "reasons": list(result.reasons),
        },
        result,
        frames[-1],
    )


def run_validation(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = VisionConfig.from_yaml(Path("configs/vision.yaml"))
    cases: list[dict[str, Any]] = []
    matrix = (
        ("one_left_1", (120,), "left", 1, 1),
        ("two_right_1", (70, 170), "right", 1, 2),
        ("three_left_2", (45, 120, 195), "left", 2, 2),
        ("three_right_2", (45, 120, 195), "right", 2, 2),
        ("four_left_2", (35, 90, 150, 205), "left", 2, 2),
        ("four_right_2", (35, 90, 150, 205), "right", 2, 3),
    )
    overlay_source: tuple[VisionDecision, RgbdFrame] | None = None
    for name, centers, side, ordinal, expected_id in matrix:
        case, decision, frame = _run_case(
            config, name, centers, side, ordinal, expected_id
        )
        cases.append(case)
        if name == "three_left_2":
            overlay_source = (decision, frame)

    case, _, _ = _run_case(
        config, "ordinal_out_of_range", (70, 170), "left", 3, None
    )
    case["passed"] = case["passed"] and "ordinal_out_of_range" in case["reasons"]
    cases.append(case)

    case, _, _ = _run_case(
        config, "horizontal_ambiguity", (116, 124), "left", 1, None
    )
    case["passed"] = case["passed"] and "horizontal_order_ambiguous" in case["reasons"]
    cases.append(case)

    # The left image-space detection has no registered depth and is excluded.
    # The remaining depth-valid bottle is therefore renumbered as index 1.
    case, _, _ = _run_case(
        config,
        "depth_region_renumbering",
        (70, 170),
        "left",
        1,
        2,
        empty_depth_for=1,
    )
    cases.append(case)

    backend, frames = _scene((70, 170))
    pipeline = VisionPipeline(config, backend)
    discovery = None
    for frame in frames[: config.track_confirmation_hits]:
        discovery = pipeline.process(frame, now_ns=frame.monotonic_ns)
    assert discovery is not None
    selected_track = next(
        track for track in discovery.tracks
        if track.state == "confirmed" and track.candidate.detection_id == 1
    )
    assert selected_track.stable_id is not None
    assert pipeline.select(selected_track.stable_id, "legacy-validation:track-loss")
    backend.candidates = ()
    lost_frame = frames[config.track_confirmation_hits]
    lost = pipeline.process(lost_frame, now_ns=lost_frame.monotonic_ns)
    cases.append(
        {
            "name": "track_loss",
            "passed": lost.status == "uncertain"
            and "target_occluded" in lost.reasons,
            "status": lost.status,
            "selected_detection_id": None,
            "reasons": list(lost.reasons),
        }
    )

    assert overlay_source is not None
    overlay_decision, overlay_frame = overlay_source
    rendered = render_overlay(
        overlay_frame.rgb,
        overlay_decision,
        RenderMetrics(fps=10.0, latency_ms=50.0),
    )
    (output_dir / "three-left-2-overlay.jpg").write_bytes(
        encode_jpeg(rendered.image)
    )
    report = {
        "schema": "thirdhand-va-offline-validation-v1",
        "robot_control_enabled": False,
        "hardware_validation": "pending",
        "camera_opened": False,
        "cases": cases,
        "passed": all(case["passed"] for case in cases),
    }
    (output_dir / "spatial-vision-offline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_validation(args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
