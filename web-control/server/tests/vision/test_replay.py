from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision.replay import ReplayFormatError, run_replay, write_metrics_atomic


FIXTURE_MANIFEST = Path(__file__).parent / "fixtures" / "synthetic_replay.json"


def test_replay_is_deterministic_and_reports_required_metrics():
    first = run_replay(FIXTURE_MANIFEST)
    second = run_replay(FIXTURE_MANIFEST)
    assert first.to_dict() == second.to_dict()
    assert first.frame_count == 3
    assert first.registration_coverage == pytest.approx(0.75)
    assert first.valid_target_cloud_frames == 1
    assert first.id_switches == 0
    assert first.track_continuity == pytest.approx(1.0)
    assert first.latency_p50_ms == pytest.approx(20.0)
    assert first.latency_p95_ms == pytest.approx(29.0)
    assert first.dry_run_approval_rate == pytest.approx(1.0 / 3.0)
    assert first.rejection_reasons == {"target_cloud_too_small": 1, "target_stale": 1}
    assert first.calibration_ids == ("sha256:synthetic-v1",)


def test_metrics_output_is_byte_deterministic_and_ends_with_newline(tmp_path):
    metrics = run_replay(FIXTURE_MANIFEST)
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_metrics_atomic(first, metrics)
    write_metrics_atomic(second, metrics)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda data: data.update(schema_version=99), "schema_version"),
        (lambda data: data.update(depth_npz="../escape.npz"), "relative"),
        (
            lambda data: data["frames"][1].update(
                monotonic_ns=data["frames"][0]["monotonic_ns"]
            ),
            "strictly increasing",
        ),
        (
            lambda data: data["frames"][1].update(
                calibration_id="sha256:different"
            ),
            "calibration",
        ),
    ],
)
def test_manifest_validation_fails_closed(tmp_path, mutation, match):
    data = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    data["depth_npz"] = str((FIXTURE_MANIFEST.parent / data["depth_npz"]).resolve())
    if match != "relative":
        # Copy the binary next to the mutated manifest and make the path relative.
        binary = Path(data["depth_npz"])
        copied = tmp_path / binary.name
        copied.write_bytes(binary.read_bytes())
        data["depth_npz"] = copied.name
    mutation(data)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReplayFormatError, match=match):
        run_replay(path)

